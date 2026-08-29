/**
 * Eastern Arabic numerals.
 *
 * docs/06 §1: "**Eastern Arabic (٠١٢٣٤٥٦٧٨٩)** for anything a child sees and
 * for dates and counts in the caregiver app. Western digits for phone numbers,
 * OTP entry and IDs."
 *
 * So this is not a formatting preference, and the exception is not an
 * afterthought: a phone number in Eastern digits is a phone number a caregiver
 * cannot check against the SIM card in their hand, and an OTP in Eastern digits
 * is one they cannot compare with the SMS. Both directions of the rule matter.
 *
 * `Intl` rather than a lookup table, because `ar-EG-u-nu-arab` also gets the
 * thousands separator and the decimal mark right, and a hand-rolled digit swap
 * would produce `1,234` with Eastern digits and a Latin comma.
 */

const FORMATTER = new Intl.NumberFormat("ar-EG-u-nu-arab");

/** For a count or an ordinal a caregiver or a child reads. */
export function arabicDigits(value: number): string {
  return FORMATTER.format(value);
}

/**
 * "٤ من ١٠".
 *
 * A fraction rather than a percentage, deliberately. docs/06 §3's copy rules
 * ban the word "score", and a percentage is a score with the word removed —
 * "40%" invites a comparison against 100 that this product never makes, while
 * "4 of 10" is a count of things a child can do.
 */
export function arabicFraction(part: number, whole: number): string {
  return `${arabicDigits(part)} من ${arabicDigits(whole)}`;
}
