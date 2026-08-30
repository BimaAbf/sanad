import type { ReactElement } from "react";

import { INK, K, PRIMARY, PRIMARY_SOFT, STROKE } from "@/components/art/frame";

/**
 * The drawings, one per curriculum skill code.
 *
 * Keyed by the same `code` the API uses (`hh_spoon`, `body_eye`), so wiring the
 * real manifest up is a lookup, not a mapping table. A code with no entry is not
 * an error — `SkillArt` falls back to the label tile, which is a legible card
 * rather than a broken image, and is what a newly seeded skill gets on the day
 * it is added and before anyone has drawn it.
 *
 * See `frame.tsx` for why these are vectors in the bundle and what rules they
 * follow. The short version: one object, centred, heavy outline, no text.
 */

const s = { stroke: INK, strokeWidth: STROKE, fill: "none" } as const;
const f = (fill: string) => ({ fill, stroke: INK, strokeWidth: STROKE }) as const;

/* ============================ body parts (10) ============================ */

function Head() {
  return (
    <>
      <circle cx="60" cy="64" r="38" {...f(K.skin)} />
      <path d="M24 56a36 36 0 0 1 72 0c-10-8-22-12-36-12S34 48 24 56Z" {...f(K.brown)} />
      <circle cx="47" cy="64" r="4.5" fill={INK} />
      <circle cx="73" cy="64" r="4.5" fill={INK} />
      <path d="M48 82a16 16 0 0 0 24 0" {...s} />
    </>
  );
}

function Hair() {
  return (
    <>
      <circle cx="60" cy="70" r="34" {...f(K.skin)} />
      <path
        d="M26 66c0-22 15-38 34-38s34 16 34 38c-4-6-6-14-8-20-6 8-14 12-26 12s-20-4-26-12c-2 6-4 14-8 20Z"
        {...f(K.brown)}
      />
      <path d="M30 62c-4 10-4 20-2 28M90 62c4 10 4 20 2 28" {...s} />
      <circle cx="49" cy="72" r="4" fill={INK} />
      <circle cx="71" cy="72" r="4" fill={INK} />
    </>
  );
}

function Eye() {
  return (
    <>
      <path d="M12 60c14-22 34-32 48-32s34 10 48 32c-14 22-34 32-48 32S26 82 12 60Z" {...f(K.white)} />
      <circle cx="60" cy="60" r="20" {...f(K.blue)} />
      <circle cx="60" cy="60" r="8.5" fill={INK} />
      <circle cx="53" cy="53" r="4" fill={K.white} stroke="none" />
      <path d="M22 36l8 8M60 24v10M98 36l-8 8" {...s} />
    </>
  );
}

function Ear() {
  return (
    <>
      <path
        d="M78 24c-20-8-42 4-44 26-1 14 6 22 8 34 2 10 10 16 20 14 9-2 12-10 10-18-2-7-8-8-8-14 0-5 4-7 9-9 13-5 18-27 5-33Z"
        {...f(K.skin)}
      />
      <path d="M62 44c-9 0-14 7-14 15 0 6 3 10 6 13" {...s} />
    </>
  );
}

function Nose() {
  return (
    <>
      <path d="M60 16c-4 20-10 34-18 46-6 9-1 18 9 18h18c10 0 15-9 9-18-8-12-14-26-18-46Z" {...f(K.skin)} />
      <ellipse cx="49" cy="70" rx="5" ry="4" fill={INK} />
      <ellipse cx="71" cy="70" rx="5" ry="4" fill={INK} />
    </>
  );
}

function Mouth() {
  return (
    <>
      <path d="M16 56c14-14 30-20 44-20s30 6 44 20c-12 22-28 32-44 32S28 78 16 56Z" {...f(K.red)} />
      <path d="M16 56h88" {...s} />
      <path d="M32 56c8-8 18-12 28-12s20 4 28 12" stroke={K.white} strokeWidth="3" fill="none" />
    </>
  );
}

function Teeth() {
  return (
    <>
      <path d="M14 52c14-16 30-24 46-24s32 8 46 24c-14 26-30 38-46 38S28 78 14 52Z" {...f(K.pink)} />
      <path d="M22 50h76v20a38 30 0 0 1-76 0Z" fill={K.white} stroke="none" />
      <path d="M22 50h76" {...s} />
      <path d="M40 50v18M60 50v20M80 50v18" stroke={INK} strokeWidth="2.5" fill="none" />
      <path d="M22 50v20a38 30 0 0 0 76 0V50" {...s} />
    </>
  );
}

function Hand() {
  return (
    <>
      <rect x="26" y="30" width="13" height="42" rx="6.5" {...f(K.skin)} />
      <rect x="42" y="18" width="13" height="54" rx="6.5" {...f(K.skin)} />
      <rect x="58" y="14" width="13" height="58" rx="6.5" {...f(K.skin)} />
      <rect x="74" y="22" width="13" height="50" rx="6.5" {...f(K.skin)} />
      <path d="M26 64c-8-6-18-2-16 8l10 20c6 12 16 18 30 18h14c14 0 24-10 24-24V56" {...f(K.skin)} />
    </>
  );
}

function Leg() {
  return (
    <>
      <path d="M44 12h30v40c0 14 4 22 4 34s-8 16-16 16-14-6-14-16 4-20 4-34Z" {...f(K.skin)} />
      <path d="M48 96c-14 2-22 6-22 12h52c0-8-6-11-14-12Z" {...f(K.skin)} />
      <path d="M44 52h34" {...s} />
    </>
  );
}

function Tummy() {
  return (
    <>
      <path d="M32 20h56c6 0 10 5 9 11l-6 62c-1 9-8 15-17 15H46c-9 0-16-6-17-15l-6-62c-1-6 3-11 9-11Z" {...f(K.yellow)} />
      <circle cx="60" cy="70" r="7" {...f(K.skin)} />
      <path d="M40 34c6 4 34 4 40 0" {...s} />
    </>
  );
}

/* ============================= household (20) ============================ */

function Toothbrush() {
  return (
    <>
      <rect x="18" y="52" width="66" height="16" rx="8" {...f(K.blue)} />
      <rect x="80" y="48" width="24" height="24" rx="7" {...f(K.white)} />
      <path d="M84 48v-14M92 48v-16M100 48v-14" stroke={K.green} strokeWidth="6" fill="none" strokeLinecap="round" />
      <path d="M84 34v-2M92 32v-2M100 34v-2" {...s} />
    </>
  );
}

function Toothpaste() {
  return (
    <>
      <path d="M34 34h52c4 0 6 3 6 7v50c0 5-3 9-8 9H36c-5 0-8-4-8-9V41c0-4 2-7 6-7Z" {...f(K.white)} />
      <path d="M28 58h64" {...s} />
      <rect x="50" y="14" width="20" height="22" rx="5" {...f(K.blue)} />
      <path d="M40 70h40M40 82h26" stroke={K.blue} strokeWidth="6" fill="none" strokeLinecap="round" />
    </>
  );
}

function Soap() {
  return (
    <>
      <rect x="20" y="52" width="66" height="42" rx="18" {...f(K.pink)} />
      <path d="M32 66c6-5 16-6 24-2" stroke={K.white} strokeWidth="4" fill="none" strokeLinecap="round" />
      <circle cx="90" cy="34" r="12" {...f(K.white)} />
      <circle cx="70" cy="22" r="8" {...f(K.white)} />
      <circle cx="98" cy="58" r="7" {...f(K.white)} />
    </>
  );
}

function Towel() {
  return (
    <>
      <rect x="14" y="24" width="92" height="10" rx="5" {...f(K.steel)} />
      <path d="M28 34h64v58c0 5-4 8-8 8H36c-4 0-8-3-8-8Z" {...f(K.orange)} />
      <path d="M28 78h64" {...s} />
      <path d="M42 34v44M78 34v44" stroke={K.white} strokeWidth="4" fill="none" />
    </>
  );
}

function Fork() {
  return (
    <>
      <path d="M38 12v30M52 12v30M66 12v30" stroke={INK} strokeWidth="7" fill="none" strokeLinecap="round" />
      <path d="M32 42h40c0 12-6 18-14 20l2 46h-16l2-46c-8-2-14-8-14-20Z" {...f(K.steel)} />
    </>
  );
}

function Spoon() {
  return (
    <>
      <ellipse cx="52" cy="38" rx="24" ry="28" {...f(K.steel)} />
      <ellipse cx="52" cy="38" rx="14" ry="18" fill={K.white} stroke="none" />
      <path d="M52 66c0 20 6 24 6 42h-12c0-18 6-22 6-42Z" {...f(K.steel)} />
    </>
  );
}

function Knife() {
  return (
    <>
      <path d="M22 24c26 0 44 12 52 30H26c-4 0-6-3-6-7Z" {...f(K.steel)} />
      <path d="M22 54h56l-2 12H26c-3 0-4-2-4-5Z" {...f(K.steel)} />
      <rect x="76" y="52" width="30" height="16" rx="7" {...f(K.brown)} />
    </>
  );
}

function Plate() {
  return (
    <>
      <ellipse cx="60" cy="62" rx="50" ry="38" {...f(K.white)} />
      <ellipse cx="60" cy="62" rx="34" ry="24" {...f(PRIMARY_SOFT)} />
      <ellipse cx="60" cy="62" rx="34" ry="24" {...s} />
    </>
  );
}

function Cup() {
  return (
    <>
      <path d="M24 30h58v46c0 12-9 20-21 20H45c-12 0-21-8-21-20Z" {...f(K.white)} />
      <path d="M82 44h10c9 0 15 6 15 14s-6 14-15 14h-8" {...f(K.white)} />
      <path d="M24 30h58" {...s} />
      <path d="M36 46v26M50 46v26" stroke={K.orange} strokeWidth="5" fill="none" strokeLinecap="round" />
    </>
  );
}

function WaterGlass() {
  return (
    <>
      <path d="M32 20h56l-8 78c-1 7-6 10-12 10H52c-6 0-11-3-12-10Z" {...f(K.white)} />
      <path d="M37 54h46l-5 44c-1 6-4 8-9 8H51c-5 0-8-2-9-8Z" fill={K.blue} stroke="none" opacity="0.85" />
      <path d="M37 54h46" {...s} />
      <path d="M32 20h56l-8 78c-1 7-6 10-12 10H52c-6 0-11-3-12-10Z" {...s} />
    </>
  );
}

function Chair() {
  return (
    <>
      <rect x="28" y="14" width="18" height="56" rx="6" {...f(K.wood)} />
      <rect x="28" y="60" width="66" height="14" rx="6" {...f(K.wood)} />
      <rect x="34" y="26" width="46" height="12" rx="5" {...f(K.wood)} />
      <rect x="34" y="72" width="12" height="34" rx="5" {...f(K.wood)} />
      <rect x="76" y="72" width="12" height="34" rx="5" {...f(K.wood)} />
    </>
  );
}

function Table() {
  return (
    <>
      <rect x="10" y="38" width="100" height="16" rx="8" {...f(K.wood)} />
      <rect x="24" y="52" width="13" height="52" rx="6" {...f(K.wood)} />
      <rect x="83" y="52" width="13" height="52" rx="6" {...f(K.wood)} />
    </>
  );
}

function Bed() {
  return (
    <>
      <rect x="10" y="34" width="16" height="66" rx="7" {...f(K.wood)} />
      <rect x="94" y="58" width="16" height="42" rx="7" {...f(K.wood)} />
      <rect x="18" y="62" width="84" height="26" rx="9" {...f(K.blue)} />
      <rect x="26" y="46" width="34" height="20" rx="9" {...f(K.white)} />
      <path d="M18 76h84" stroke={K.white} strokeWidth="4" fill="none" />
    </>
  );
}

function Pillow() {
  return (
    <>
      <path d="M20 34h80c8 0 12 6 12 14v24c0 8-4 14-12 14H20c-8 0-12-6-12-14V48c0-8 4-14 12-14Z" {...f(K.white)} />
      <path d="M26 46c8 14 8 22 0 34M94 46c-8 14-8 22 0 34" {...s} />
    </>
  );
}

function Door() {
  return (
    <>
      <rect x="26" y="10" width="68" height="100" rx="10" {...f(K.wood)} />
      <rect x="38" y="24" width="44" height="32" rx="6" {...f(K.brown)} />
      <circle cx="42" cy="76" r="6.5" {...f(K.yellow)} />
    </>
  );
}

function Window() {
  return (
    <>
      <rect x="16" y="16" width="88" height="88" rx="10" {...f(K.blue)} />
      <path d="M60 16v88M16 60h88" stroke={K.white} strokeWidth="8" fill="none" />
      <rect x="16" y="16" width="88" height="88" rx="10" {...s} />
      <circle cx="38" cy="38" r="8" fill={K.yellow} stroke="none" />
    </>
  );
}

function Shoes() {
  return (
    <>
      <path d="M18 44h26c6 14 18 20 34 24 12 3 20 8 20 18v6H18Z" {...f(K.blue)} />
      <path d="M14 92h94c0 8-4 12-12 12H26c-8 0-12-4-12-12Z" {...f(K.black)} />
      <path d="M44 52c8 6 16 10 24 12" stroke={K.white} strokeWidth="4" fill="none" />
    </>
  );
}

function Bag() {
  return (
    <>
      <path d="M42 46V36a18 18 0 0 1 36 0v10" {...s} />
      <rect x="18" y="46" width="84" height="58" rx="12" {...f(K.purple)} />
      <rect x="18" y="66" width="84" height="12" fill={K.white} stroke="none" opacity="0.5" />
      <rect x="18" y="46" width="84" height="58" rx="12" {...s} />
    </>
  );
}

function Clothes() {
  return (
    <>
      <path d="M42 20h36l26 16-12 22-14-8v54H42V50l-14 8-12-22Z" {...f(K.green)} />
      <path d="M42 20c0 10 8 16 18 16s18-6 18-16" {...s} />
    </>
  );
}

function Comb() {
  return (
    <>
      <rect x="12" y="30" width="96" height="22" rx="9" {...f(K.purple)} />
      <path
        d="M22 52v34M34 52v34M46 52v34M58 52v34M70 52v34M82 52v34M94 52v34"
        stroke={INK}
        strokeWidth="6"
        fill="none"
        strokeLinecap="round"
      />
    </>
  );
}

/* ============================== social (10) ============================== */

function Sun() {
  return (
    <>
      <circle cx="60" cy="60" r="26" {...f(K.yellow)} />
      <path
        d="M60 14v-8M60 114v-8M14 60H6M114 60h-8M27 27l-6-6M99 99l-6-6M93 27l6-6M21 99l6-6"
        stroke={K.orange}
        strokeWidth="7"
        fill="none"
        strokeLinecap="round"
      />
      <circle cx="52" cy="56" r="3.5" fill={INK} />
      <circle cx="68" cy="56" r="3.5" fill={INK} />
      <path d="M52 70a10 10 0 0 0 16 0" {...s} />
    </>
  );
}

function WaveGoodbye() {
  return (
    <>
      <path d="M34 40c0-6 8-6 8 0v22M46 30c0-6 8-6 8 0v30M58 28c0-6 8-6 8 0v32M70 36c0-6 8-6 8 0v26" {...f(K.skin)} />
      <path d="M34 58c-8-4-14 2-10 10l8 16c6 12 16 18 28 18 16 0 22-12 22-26V56" {...f(K.skin)} />
      <path d="M92 26c6 6 6 16 0 22M104 18c10 12 10 30 0 42" stroke={PRIMARY} strokeWidth="5" fill="none" strokeLinecap="round" />
    </>
  );
}

function HeartInHand() {
  return (
    <>
      <path
        d="M60 40c-6-10-24-8-24 6 0 12 16 20 24 28 8-8 24-16 24-28 0-14-18-16-24-6Z"
        {...f(K.pink)}
      />
      <path d="M18 78c0-8 8-10 14-6l12 8h24c8 0 14 4 14 10s-6 10-14 10H44c-14 0-26-8-26-22Z" {...f(K.skin)} />
    </>
  );
}

function OpenPalms() {
  return (
    <>
      <path d="M8 62c0-8 8-12 14-6l10 10h18c8 0 12 6 12 12s-6 12-14 12H36C20 90 8 78 8 62Z" {...f(K.skin)} />
      <path d="M112 62c0-8-8-12-14-6l-10 10H70c-8 0-12 6-12 12s6 12 14 12h16c16 0 24-12 24-28Z" {...f(K.skin)} />
      <path d="M32 46c0-6 8-6 8 0M80 46c0-6 8-6 8 0" {...s} />
    </>
  );
}

function TickYes() {
  return (
    <>
      <circle cx="60" cy="60" r="46" {...f(PRIMARY_SOFT)} />
      <path d="M36 62l16 18 34-38" stroke={PRIMARY} strokeWidth="11" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </>
  );
}

function StopNo() {
  return (
    <>
      <path d="M34 44c0-6 8-6 8 0v18M46 32c0-6 8-6 8 0v30M58 30c0-6 8-6 8 0v32M70 40c0-6 8-6 8 0v22" {...f(K.skin)} />
      <path d="M34 60c-8-4-14 2-10 10l8 16c6 12 16 18 28 18 16 0 22-12 22-26V58" {...f(K.skin)} />
      <path d="M96 34l-14 14M82 34l14 14" stroke={K.purple} strokeWidth="6" fill="none" strokeLinecap="round" />
    </>
  );
}

function ComeHere() {
  return (
    <>
      <path d="M46 34c0-6 8-6 8 0v26M58 30c0-6 8-6 8 0v30M70 34c0-6 8-6 8 0v26" {...f(K.skin)} />
      <path d="M46 56c-8-4-14 2-10 10l8 16c6 12 16 18 28 18 16 0 22-12 22-26V54" {...f(K.skin)} />
      <path d="M28 44c-8 6-8 22 0 30" stroke={PRIMARY} strokeWidth="5" fill="none" strokeLinecap="round" />
      <path d="M14 36c-12 12-12 36 0 46" stroke={PRIMARY} strokeWidth="5" fill="none" strokeLinecap="round" />
    </>
  );
}

function FaceDad() {
  return (
    <>
      <circle cx="60" cy="62" r="38" {...f(K.skin)} />
      <path d="M24 52a36 36 0 0 1 72 0c-10-10-22-14-36-14S34 42 24 52Z" {...f(K.black)} />
      <circle cx="47" cy="62" r="4.5" fill={INK} />
      <circle cx="73" cy="62" r="4.5" fill={INK} />
      <path d="M46 80h28c0 6-6 10-14 10s-14-4-14-10Z" {...f(K.black)} />
      <path d="M46 80c4-6 24-6 28 0" {...s} />
    </>
  );
}

function FaceMum() {
  return (
    <>
      <circle cx="60" cy="64" r="36" {...f(K.skin)} />
      <path
        d="M22 68C22 42 39 26 60 26s38 16 38 42c0-12-6-18-10-24-8 8-16 12-28 12s-20-4-28-12c-4 6-10 12-10 24Z"
        {...f(K.brown)}
      />
      <path d="M24 62c-6 12-6 26-2 36M96 62c6 12 6 26 2 36" {...f(K.brown)} />
      <circle cx="48" cy="66" r="4.5" fill={INK} />
      <circle cx="72" cy="66" r="4.5" fill={INK} />
      <path d="M50 84a14 14 0 0 0 20 0" {...s} />
    </>
  );
}

function PointToSelf() {
  return (
    <>
      <circle cx="60" cy="30" r="20" {...f(K.skin)} />
      <path d="M28 108c0-20 14-32 32-32s32 12 32 32Z" {...f(K.orange)} />
      <path d="M42 92c0-6 8-6 8 0M84 78c6 0 8 8 2 12l-18 12c-6 4-12 0-12-6s4-8 8-10Z" {...f(K.skin)} />
      <circle cx="53" cy="28" r="3.5" fill={INK} />
      <circle cx="67" cy="28" r="3.5" fill={INK} />
    </>
  );
}

/* ====================== letter keyword pictures (16) ===================== */

function Lion() {
  return (
    <>
      <circle cx="60" cy="62" r="44" {...f(K.orange)} />
      <circle cx="60" cy="62" r="30" {...f(K.yellow)} />
      <circle cx="49" cy="56" r="4.5" fill={INK} />
      <circle cx="71" cy="56" r="4.5" fill={INK} />
      <path d="M53 72h14l-7 8Z" {...f(K.brown)} />
      <path d="M60 80v6M48 88c6 4 18 4 24 0" {...s} />
    </>
  );
}

function Duck() {
  return (
    <>
      <ellipse cx="58" cy="76" rx="38" ry="26" {...f(K.yellow)} />
      <circle cx="86" cy="46" r="20" {...f(K.yellow)} />
      <path d="M104 44h14c0 8-6 12-14 12Z" {...f(K.orange)} />
      <circle cx="90" cy="40" r="3.5" fill={INK} />
      <path d="M40 74c8-8 22-8 30 0" {...s} />
      <path d="M52 100c0 6 4 8 8 8M74 100c0 6 4 8 8 8" stroke={K.orange} strokeWidth="6" fill="none" strokeLinecap="round" />
    </>
  );
}

function Apple() {
  return (
    <>
      <path
        d="M60 32c-8-8-30-6-34 14-4 20 8 46 22 52 6 3 8 0 12 0s6 3 12 0c14-6 26-32 22-52-4-20-26-22-34-14Z"
        {...f(K.red)}
      />
      <path d="M60 32V16" stroke={K.brown} strokeWidth="6" fill="none" strokeLinecap="round" />
      <path d="M62 22c8-10 20-10 24-4-4 8-16 12-24 4Z" {...f(K.green)} />
    </>
  );
}

function Fish() {
  return (
    <>
      <path d="M84 60c0 18-16 30-34 30S14 78 14 60s18-30 36-30 34 12 34 30Z" {...f(K.blue)} />
      <path d="M84 60l24-20v40Z" {...f(K.blue)} />
      <circle cx="32" cy="52" r="5" fill={K.white} />
      <circle cx="32" cy="52" r="2.5" fill={INK} />
      <path d="M56 42c6 12 6 24 0 36" {...s} />
    </>
  );
}

function Moon() {
  return (
    <>
      <path d="M76 12a48 48 0 1 0 0 96 40 40 0 0 1 0-96Z" {...f(K.yellow)} />
      <circle cx="98" cy="26" r="6" {...f(K.white)} />
      <circle cx="104" cy="52" r="4" {...f(K.white)} />
    </>
  );
}

function Flower() {
  return (
    <>
      <path d="M60 60V108" stroke={K.green} strokeWidth="7" fill="none" strokeLinecap="round" />
      <path d="M60 88c-14 0-22-8-22-16 14 0 22 8 22 16Z" {...f(K.green)} />
      <circle cx="60" cy="30" r="16" {...f(K.pink)} />
      <circle cx="34" cy="52" r="16" {...f(K.pink)} />
      <circle cx="86" cy="52" r="16" {...f(K.pink)} />
      <circle cx="44" cy="80" r="16" {...f(K.pink)} />
      <circle cx="76" cy="80" r="16" {...f(K.pink)} />
      <circle cx="60" cy="58" r="16" {...f(K.yellow)} />
    </>
  );
}

function Banana() {
  return (
    <>
      <path
        d="M20 34c0 40 26 62 60 62 12 0 20-4 24-10-26 2-52-18-60-52-4-14-24-14-24 0Z"
        {...f(K.yellow)}
      />
      <path d="M22 30c-6-2-8 2-6 6M104 86c6 2 8 6 2 8" {...f(K.brown)} />
    </>
  );
}

function Bee() {
  return (
    <>
      <ellipse cx="36" cy="34" rx="18" ry="14" {...f(K.white)} />
      <ellipse cx="80" cy="34" rx="18" ry="14" {...f(K.white)} />
      <ellipse cx="60" cy="66" rx="34" ry="28" {...f(K.yellow)} />
      <path d="M48 42c-4 16-4 32 0 46M68 42c4 16 4 32 0 46" stroke={INK} strokeWidth="9" fill="none" />
      <ellipse cx="60" cy="66" rx="34" ry="28" {...s} />
      <circle cx="46" cy="60" r="3.5" fill={INK} />
      <circle cx="74" cy="60" r="3.5" fill={INK} />
    </>
  );
}

function Elephant() {
  return (
    <>
      <ellipse cx="54" cy="62" rx="40" ry="34" {...f(K.steel)} />
      <ellipse cx="26" cy="54" rx="20" ry="24" {...f(K.steel)} />
      <path d="M88 66c8 10 14 20 8 32-4 8-16 6-16-4 0-8 4-14 4-22" {...f(K.steel)} />
      <circle cx="72" cy="52" r="4.5" fill={INK} />
      <path d="M40 92v14M64 94v12" stroke={INK} strokeWidth="8" fill="none" strokeLinecap="round" />
    </>
  );
}

function Book() {
  return (
    <>
      <path d="M60 30c-12-8-30-10-46-8v66c16-2 34 0 46 8Z" {...f(K.red)} />
      <path d="M60 30c12-8 30-10 46-8v66c-16-2-34 0-46 8Z" {...f(K.blue)} />
      <path d="M60 30v66" {...s} />
      <path d="M24 40c10-1 20 0 26 3M70 43c6-3 16-4 26-3" stroke={K.white} strokeWidth="3.5" fill="none" />
    </>
  );
}

function Plane() {
  return (
    <>
      <path d="M8 62l40-8 22-32c4-6 14-6 14 4v24l28 6c6 1 6 9 0 10l-28 6v24c0 10-10 10-14 4L48 68 8 62Z" {...f(K.white)} />
      <path d="M70 46v28" stroke={K.blue} strokeWidth="5" fill="none" />
      <circle cx="90" cy="60" r="4" fill={K.blue} />
    </>
  );
}

function Lemon() {
  return (
    <>
      <ellipse cx="58" cy="64" rx="42" ry="32" {...f(K.yellow)} />
      <path d="M100 64c8 0 10-4 10-8-6-2-10 2-10 8ZM16 64c-8 0-10-4-10-8 6-2 10 2 10 8Z" {...f(K.yellow)} />
      <path d="M46 24c8-10 22-10 28-2-8 8-22 8-28 2Z" {...f(K.green)} />
    </>
  );
}

function Pomegranate() {
  return (
    <>
      <circle cx="60" cy="68" r="38" {...f(K.red)} />
      <path d="M52 30h16l-4-8h4l-6-10-6 10h4Z" {...f(K.green)} />
      <circle cx="48" cy="62" r="5" fill={K.white} stroke="none" opacity="0.55" />
      <circle cx="66" cy="76" r="5" fill={K.white} stroke="none" opacity="0.55" />
      <circle cx="70" cy="56" r="4" fill={K.white} stroke="none" opacity="0.55" />
    </>
  );
}

function Gift() {
  return (
    <>
      <rect x="16" y="46" width="88" height="58" rx="10" {...f(K.purple)} />
      <rect x="10" y="30" width="100" height="20" rx="8" {...f(K.pink)} />
      <path d="M60 30v74" stroke={K.yellow} strokeWidth="10" fill="none" />
      <path d="M60 30c-14-2-22-6-22-12s12-8 22 12c10-20 22-18 22-12s-8 10-22 12Z" {...f(K.yellow)} />
    </>
  );
}

function Envelope() {
  return (
    <>
      <rect x="10" y="30" width="100" height="62" rx="10" {...f(K.white)} />
      <path d="M10 38l50 34 50-34" {...s} />
      <path d="M10 84l34-26M110 84L76 58" {...s} />
    </>
  );
}

function Corn() {
  return (
    <>
      <ellipse cx="60" cy="62" rx="24" ry="46" {...f(K.yellow)} />
      <path d="M46 30c0 40 0 50 0 64M60 24v76M74 30c0 40 0 50 0 64" stroke={K.orange} strokeWidth="4" fill="none" />
      <path d="M36 60c-16 6-20 26-8 42 14-4 20-20 18-34ZM84 60c16 6 20 26 8 42-14-4-20-20-18-34Z" {...f(K.green)} />
    </>
  );
}

/* ================================ registry =============================== */

export const OBJECT_ART: Record<string, () => ReactElement> = {
  // body parts
  body_head: Head,
  body_hair: Hair,
  body_eye: Eye,
  body_ear: Ear,
  body_nose: Nose,
  body_mouth: Mouth,
  body_teeth: Teeth,
  body_hand: Hand,
  body_leg: Leg,
  body_tummy: Tummy,

  // household
  hh_toothbrush: Toothbrush,
  hh_toothpaste: Toothpaste,
  hh_soap: Soap,
  hh_towel: Towel,
  hh_fork: Fork,
  hh_spoon: Spoon,
  hh_knife: Knife,
  hh_plate: Plate,
  hh_cup: Cup,
  hh_water_glass: WaterGlass,
  hh_chair: Chair,
  hh_table: Table,
  hh_bed: Bed,
  hh_pillow: Pillow,
  hh_door: Door,
  hh_window: Window,
  hh_shoes: Shoes,
  hh_bag: Bag,
  hh_clothes: Clothes,
  hh_comb: Comb,

  // social
  social_good_morning: Sun,
  social_goodbye: WaveGoodbye,
  social_thanks: HeartInHand,
  social_please: OpenPalms,
  social_yes: TickYes,
  social_no: StopNo,
  social_come: ComeHere,
  social_dad: FaceDad,
  social_mum: FaceMum,
  social_my_name: PointToSelf,
};

/**
 * Pictures for the letter keywords, keyed by letter code.
 *
 * Deliberately partial. A letter's *card* is always the glyph tile — identical
 * for all 28, because a child learning letter shapes should not have to work out
 * why some cards are pictures and some are not. These pictures appear only in
 * the story moment, where the keyword is being taught ("أ … أسد"), and a letter
 * without one simply shows the glyph on its own.
 */
export const KEYWORD_ART: Record<string, () => ReactElement> = {
  letter_alef: Lion, // أسد
  letter_baa: Duck, // بطة
  letter_taa: Apple, // تفاحة
  letter_thal: Corn, // ذرة
  letter_raa: Pomegranate, // رمانة
  letter_seen: Fish, // سمكة
  letter_sheen: Sun, // شمس
  letter_tah: Plane, // طيارة
  letter_zah: Envelope, // ظرف
  letter_faa: Elephant, // فيل
  letter_qaf: Moon, // قمر
  letter_kaf: Book, // كتاب
  letter_lam: Lemon, // ليمونة
  letter_meem: Banana, // موزة
  letter_noon: Bee, // نحلة
  letter_haa2: Gift, // هدية
  letter_waw: Flower, // وردة
  letter_yaa: Hand, // يد
};
