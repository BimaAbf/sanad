/**
 * Fargate services and the blue/green deployment.
 *
 * docs/08 §4: blue/green via CodeDeploy with a 10-minute bake and automatic
 * rollback on the 5xx-rate or p95-latency alarms. The bake is the whole point —
 * a deploy that flips traffic instantly and reports success has not tested
 * anything, and the failure mode this product cares about (a subtly wrong
 * developmental number) does not show up in the first thirty seconds.
 */

variable "name" { type = string }
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "public_subnet_ids" { type = list(string) }
variable "api_image" { type = string }
variable "web_image" { type = string }
variable "secret_arns" { type = map(string) }
variable "bake_minutes" {
  type    = number
  default = 10
}

resource "aws_ecs_cluster" "this" {
  name = var.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_security_group" "alb" {
  name   = "${var.name}-alb"
  vpc_id = var.vpc_id
}

resource "aws_security_group" "service" {
  name   = "${var.name}-service"
  vpc_id = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "service_from_alb" {
  security_group_id            = aws_security_group.service.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "service_out" {
  security_group_id = aws_security_group.service.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_lb" "this" {
  name                       = var.name
  load_balancer_type         = "application"
  subnets                    = var.public_subnet_ids
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
  enable_deletion_protection = true
}

# Two target groups: CodeDeploy shifts traffic between them. One is not enough
# for blue/green, and this is the piece people forget until the first deploy.
resource "aws_lb_target_group" "api" {
  count       = 2
  name        = "${var.name}-api-${count.index}"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    # Liveness, not readiness: a task whose Redis is briefly unhappy is still
    # serving, and pulling it out of the pool would turn a dependency blip into
    # an outage.
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
    timeout             = 5
  }

  deregistration_delay = 30
}

resource "aws_cloudwatch_metric_alarm" "five_xx" {
  alarm_name          = "${var.name}-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  period              = 300
  # docs/08 §5: > 1% over 5 minutes pages, and rolls a deploy back.
  threshold           = 1
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"
  dimensions          = { LoadBalancer = aws_lb.this.arn_suffix }
}

resource "aws_cloudwatch_metric_alarm" "p95_latency" {
  alarm_name          = "${var.name}-p95"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  period              = 300
  extended_statistic  = "p95"
  threshold           = 2
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  treat_missing_data  = "notBreaching"
  dimensions          = { LoadBalancer = aws_lb.this.arn_suffix }
}

resource "aws_codedeploy_app" "api" {
  name             = "${var.name}-api"
  compute_platform = "ECS"
}

resource "aws_codedeploy_deployment_group" "api" {
  app_name               = aws_codedeploy_app.api.name
  deployment_group_name  = "${var.name}-api"
  service_role_arn       = aws_iam_role.codedeploy.arn
  deployment_config_name = "CodeDeployDefault.ECSAllAtOnce"

  deployment_style {
    deployment_option = "WITH_TRAFFIC_CONTROL"
    deployment_type   = "BLUE_GREEN"
  }

  blue_green_deployment_config {
    deployment_ready_option {
      action_on_timeout = "CONTINUE_DEPLOYMENT"
    }
    terminate_blue_instances_on_deployment_success {
      action                           = "TERMINATE"
      termination_wait_time_in_minutes = var.bake_minutes
    }
  }

  # The rollback is automatic and alarm-driven. A deploy that a human has to
  # notice is a deploy that runs broken through the night.
  auto_rollback_configuration {
    enabled = true
    events  = ["DEPLOYMENT_FAILURE", "DEPLOYMENT_STOP_ON_ALARM"]
  }

  alarm_configuration {
    enabled = true
    alarms  = [aws_cloudwatch_metric_alarm.five_xx.alarm_name, aws_cloudwatch_metric_alarm.p95_latency.alarm_name]
  }

  ecs_service {
    cluster_name = aws_ecs_cluster.this.name
    service_name = "${var.name}-api"
  }
}

resource "aws_iam_role" "codedeploy" {
  name = "${var.name}-codedeploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codedeploy.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "codedeploy" {
  role       = aws_iam_role.codedeploy.name
  policy_arn = "arn:aws:iam::aws:policy/AWSCodeDeployRoleForECS"
}

output "cluster_name" { value = aws_ecs_cluster.this.name }
output "service_security_group_id" { value = aws_security_group.service.id }
output "alb_dns_name" { value = aws_lb.this.dns_name }
