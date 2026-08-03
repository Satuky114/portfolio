"use client";

import { motion } from "framer-motion";
import { Aperture, Play, Film } from "lucide-react";
import { useI18n } from "@/app/[locale]/ClientIntlProvider";
import { SectionWrapper } from "@/components/ui/SectionWrapper";
import { SectionHeading } from "@/components/ui/SectionHeading";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { asset, cn } from "@/lib/utils";

/* ============================================================
 * Work data — TODO: replace with real works
 * ------------------------------------------------------------
 * Each entry is ONE frame on the contact sheet.
 *
 * To publish a piece, append an object to the relevant array:
 *
 *   { id: "lf-1",
 *     src: "/longform/my-piece.jpg",          // path under /public
 *     titleZh: "推文标题",
 *     titleEn: "Article Title",
 *     href: "https://mp.weixin.qq.com/s/..."  // optional outbound link
 *   }
 *
 * Leave `src: null` (or omit the entry) to keep an "unexposed"
 * placeholder. Real works render first; the remaining slots
 * auto-pad with placeholders up to MIN_SLOTS, then the grid
 * reflows as more are added. A partly-filled array reads as a
 * partly-shot roll — still intentional. Frame numbers auto-
 * increment from array index; no JSX edits needed to grow it.
 * ============================================================ */

interface Work {
  id: string;
  /** path under /public (asset() adds the basePath); null = reserved */
  src: string | null;
  titleZh: string;
  titleEn: string;
  /** optional outbound link (article / video URL) */
  href?: string;
}

// Sub-gallery 01 — 公众号长图 (tall vertical long-form)
const LONGFORM_WORKS: Work[] = [
  // { id: "lf-1", src: "/longform/example.jpg",
  //   titleZh: "推文标题", titleEn: "Article Title",
  //   href: "https://mp.weixin.qq.com/s/..." },
];

// Sub-gallery 02 — AIGC视频 (landscape video thumbnails)
const VIDEO_WORKS: Work[] = [
  // { id: "vd-1", src: "/video/example.jpg",
  //   titleZh: "视频标题", titleEn: "Video Title",
  //   href: "https://..." },
];

// Minimum visible slots — keeps the empty state dense & intentional.
const MIN_SLOTS = 4;

type Variant = "longform" | "video";

interface Slot {
  work: Work | null;
  index: number;
}

/** Real works first, then null placeholders up to MIN_SLOTS. */
function buildRoll(works: Work[]): Slot[] {
  const padding = Math.max(0, MIN_SLOTS - works.length);
  const slots: (Work | null)[] = [
    ...works,
    ...Array.from({ length: padding }).map(() => null),
  ];
  return slots.map((work, index) => ({ work, index }));
}

/* ============================================================
 * Perforated filmstrip edge — decorative sprocket holes
 * ============================================================ */
function Filmstrip() {
  return (
    <div
      aria-hidden="true"
      className="h-4 w-full border-y border-border bg-bg-surface"
      style={{
        backgroundImage:
          "repeating-linear-gradient(to right, transparent 0, transparent 9px, var(--bg-primary) 9px, var(--bg-primary) 19px, transparent 19px, transparent 30px)",
      }}
    />
  );
}

/* ============================================================
 * ExposureBar — a restrained "still developing" cue (one per panel)
 * ============================================================ */
function ExposureBar({
  accent,
  label,
  percent,
  reduced,
}: {
  accent: string;
  label: string;
  percent: number;
  reduced: boolean;
}) {
  return (
    <div className="min-w-[116px] shrink-0">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span
          className="font-mono text-[9px] uppercase tracking-[0.2em]"
          style={{ color: accent }}
        >
          {label}
        </span>
        <span className="font-mono text-[9px] text-text-tertiary">{percent}%</span>
      </div>
      <div className="relative h-[3px] overflow-hidden rounded-full border border-border/60 bg-bg-surface">
        <motion.div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ background: accent }}
          initial={reduced ? { width: `${percent}%` } : { width: "0%" }}
          whileInView={{ width: `${percent}%` }}
          viewport={{ once: true, margin: "-40px" }}
          transition={{ duration: 1.1, ease: "easeOut", delay: 0.25 }}
        />
        {!reduced && (
          <motion.div
            aria-hidden="true"
            className="absolute inset-y-0 w-1/3"
            style={{
              background: `color-mix(in srgb, ${accent} 45%, transparent)`,
            }}
            animate={{ x: ["-130%", "330%"] }}
            transition={{
              duration: 2.6,
              repeat: Infinity,
              ease: "easeInOut",
              repeatDelay: 0.8,
            }}
          />
        )}
      </div>
    </div>
  );
}

/* ============================================================
 * Filled media — image + legibility gradient + (video) play button
 * ============================================================ */
function Media({ variant, src, alt }: { variant: Variant; src: string; alt: string }) {
  return (
    <>
      <img
        src={asset(src)}
        alt={alt}
        loading="lazy"
        className={cn(
          "h-full w-full object-cover transition-transform duration-700 group-hover/frame:scale-[1.04]",
          variant === "longform" ? "object-top" : "object-center",
        )}
      />
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 h-1/3"
        style={{ background: "linear-gradient(to top, var(--bg-primary), transparent)" }}
      />
      {variant === "video" && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/15 transition-colors duration-300 group-hover/frame:bg-black/25">
          <span className="flex h-11 w-11 items-center justify-center rounded-full bg-bg-primary/70 text-text-primary shadow-lg backdrop-blur-md transition-all duration-300 group-hover/frame:scale-110 group-hover/frame:bg-accent3 group-hover/frame:text-bg-primary">
            <Play size={18} className="ml-0.5" />
          </span>
        </div>
      )}
    </>
  );
}

/* ============================================================
 * One frame — real work OR "unexposed" placeholder
 * ============================================================ */
interface FrameProps {
  slot: Slot;
  variant: Variant;
  glow: string;
  locale: string;
  reduced: boolean;
  unexposedLabel: string;
  unexposedNote: string;
}

function Frame({
  slot,
  variant,
  glow,
  locale,
  reduced,
  unexposedLabel,
  unexposedNote,
}: FrameProps) {
  const { work, index } = slot;
  const frameNo = String(index + 1).padStart(2, "0");
  const filled = work !== null && Boolean(work.src);
  const ratio =
    variant === "longform" ? "aspect-[4/5] sm:aspect-[3/5]" : "aspect-video";
  const title = work ? (locale === "zh" ? work.titleZh : work.titleEn) : "";

  return (
    <motion.li
      initial={reduced ? {} : { opacity: 0, y: 18 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-40px" }}
      transition={{
        delay: (index % MIN_SLOTS) * 0.07,
        duration: 0.5,
        ease: "easeOut",
      }}
      className="list-none"
    >
      <div
        className={cn(
          "group/frame relative overflow-hidden rounded-md border border-border bg-bg-primary transition-colors duration-500 group-hover/frame:border-border-hover",
          ratio,
        )}
      >
        {/* Edge-printed frame number — always visible, like a real contact sheet */}
        <span className="absolute left-2 top-1.5 z-20 rounded bg-bg-primary/55 px-1.5 py-0.5 font-mono text-[10px] leading-none tracking-[0.15em] text-text-tertiary/80 backdrop-blur-sm">
          {frameNo}
        </span>

        {filled && work ? (
          work.href ? (
            <a
              href={work.href}
              target="_blank"
              rel="noopener noreferrer"
              className="block h-full w-full"
              aria-label={title}
            >
              <Media variant={variant} src={work.src as string} alt={title} />
            </a>
          ) : (
            <div className="block h-full w-full" role="img" aria-label={title}>
              <Media variant={variant} src={work.src as string} alt={title} />
            </div>
          )
        ) : (
          <>
            {/* Safelight wash — static radial glow, brightens on hover (CSS-only, reduced-safe) */}
            <div
              aria-hidden="true"
              className="absolute inset-0 z-0 opacity-50 transition-opacity duration-500 group-hover/frame:opacity-90"
              style={{
                background: `radial-gradient(circle at 50% 42%, ${glow} 0%, transparent 62%)`,
              }}
            />
            <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-1.5 px-2 text-center">
              {variant === "video" ? (
                <span className="flex h-10 w-10 items-center justify-center rounded-full border border-dashed border-text-tertiary/40 text-text-tertiary/45">
                  <Play size={14} className="ml-0.5" />
                </span>
              ) : (
                <Aperture
                  size={22}
                  strokeWidth={1.5}
                  className="text-text-tertiary/45 transition-colors duration-500 group-hover/frame:text-text-tertiary/75"
                />
              )}
              <span className="font-mono text-[9px] uppercase tracking-[0.25em] text-text-tertiary/75">
                {unexposedLabel}
              </span>
              <span className="font-mono text-[8px] uppercase tracking-[0.2em] text-text-tertiary/40">
                {unexposedNote}
              </span>
            </div>
          </>
        )}
      </div>
    </motion.li>
  );
}

/* ============================================================
 * One contact-sheet panel (a sub-gallery)
 * ============================================================ */
interface ContactSheetProps {
  sheetNo: string;
  variant: Variant;
  accent: string;
  glow: string;
  works: Work[];
  headingId: string;
  sheetLabel: string;
  process: string;
  label: string;
  description: string;
  framesUnit: string;
  unexposedLabel: string;
  unexposedNote: string;
  developingLabel: string;
  developedLabel: string;
  srNote: string;
  locale: string;
  reduced: boolean;
}

function ContactSheet({
  sheetNo,
  variant,
  accent,
  glow,
  works,
  headingId,
  sheetLabel,
  process,
  label,
  description,
  framesUnit,
  unexposedLabel,
  unexposedNote,
  developingLabel,
  developedLabel,
  srNote,
  locale,
  reduced,
}: ContactSheetProps) {
  const slots = buildRoll(works);
  const total = slots.length;
  const filled = slots.filter((s) => s.work !== null && Boolean(s.work.src)).length;
  const isDeveloping = filled < total;
  const exposurePct = Math.max(12, total ? Math.round((filled / total) * 100) : 12);

  return (
    <motion.section
      aria-labelledby={headingId}
      initial={reduced ? {} : { opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.6, ease: "easeOut" }}
      className="relative overflow-hidden rounded-2xl border border-border bg-bg-elevated shadow-xl shadow-black/20"
    >
      {/* Header — glowing accent dot + canister eyebrow + label + frame count */}
      <div className="flex items-end justify-between gap-4 px-5 pb-4 pt-5 sm:px-7">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className="inline-block h-2 w-2 shrink-0 rounded-full"
            style={{ background: accent, boxShadow: `0 0 12px ${accent}` }}
          />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[10px] uppercase tracking-[0.25em] text-text-tertiary">
              <span>
                {sheetLabel} {sheetNo}
              </span>
              <span className="opacity-50">— {process}</span>
            </div>
            <h3
              id={headingId}
              className="truncate font-display text-lg font-bold text-text-primary sm:text-xl"
            >
              {label}
            </h3>
          </div>
        </div>
        <div className="shrink-0 whitespace-nowrap font-mono text-[10px] uppercase tracking-[0.2em] text-text-tertiary">
          {filled}/{total} · {framesUnit}
        </div>
      </div>

      <Filmstrip />

      {/* Frames on the dark "film base" */}
      <div className="bg-bg-primary px-4 py-5 sm:px-6 sm:py-6">
        <ul role="list" className="grid grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-4">
          {slots.map((slot) => (
            <Frame
              key={slot.work?.id ?? `${variant}-empty-${slot.index}`}
              slot={slot}
              variant={variant}
              glow={glow}
              locale={locale}
              reduced={reduced}
              unexposedLabel={unexposedLabel}
              unexposedNote={unexposedNote}
            />
          ))}
        </ul>
        <p className="sr-only">{srNote}</p>
      </div>

      <Filmstrip />

      {/* Footer — description + developing/live status */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-t border-border px-5 py-4 sm:px-7">
        <div className="flex min-w-0 items-center gap-2.5">
          <Film size={14} className="shrink-0 text-text-tertiary" />
          <p className="text-xs leading-relaxed text-text-secondary sm:text-sm">
            {description}
          </p>
        </div>
        {isDeveloping ? (
          <ExposureBar
            accent={accent}
            label={developingLabel}
            percent={exposurePct}
            reduced={reduced}
          />
        ) : (
          <span
            className="shrink-0 rounded-full border px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.2em]"
            style={{
              color: accent,
              borderColor: `color-mix(in srgb, ${accent} 35%, transparent)`,
              backgroundColor: `color-mix(in srgb, ${accent} 10%, transparent)`,
            }}
          >
            {developedLabel}
          </span>
        )}
      </div>
    </motion.section>
  );
}

/* ============================================================
 * Portfolio — two matched contact sheets (stills + motion)
 * ============================================================ */
export function Portfolio() {
  const { t, locale } = useI18n();
  const reduced = useReducedMotion();

  return (
    <SectionWrapper
      id="portfolio"
      gradientBottom
      orb={{ size: 520, color: "var(--accent)", position: "top-1/4 -left-28" }}
    >
      <SectionHeading
        title={t("portfolio.title")}
        subtitle={t("portfolio.subtitle")}
      />

      <div className="mx-auto max-w-6xl space-y-10 md:space-y-14">
        <ContactSheet
          sheetNo="01"
          variant="longform"
          accent="var(--accent)"
          glow="var(--accent-glow)"
          works={LONGFORM_WORKS}
          headingId="portfolio-longform-title"
          sheetLabel={t("portfolio.sheetLabel")}
          process={t("portfolio.longform.process")}
          label={t("portfolio.longform.label")}
          description={t("portfolio.longform.description")}
          framesUnit={t("portfolio.framesUnit")}
          unexposedLabel={t("portfolio.unexposedLabel")}
          unexposedNote={t("portfolio.unexposedNote")}
          developingLabel={t("portfolio.developingLabel")}
          developedLabel={t("portfolio.developedLabel")}
          srNote={t("portfolio.srNote")}
          locale={locale}
          reduced={reduced}
        />
        <ContactSheet
          sheetNo="02"
          variant="video"
          accent="var(--accent3)"
          glow="var(--accent3-glow)"
          works={VIDEO_WORKS}
          headingId="portfolio-video-title"
          sheetLabel={t("portfolio.sheetLabel")}
          process={t("portfolio.video.process")}
          label={t("portfolio.video.label")}
          description={t("portfolio.video.description")}
          framesUnit={t("portfolio.framesUnit")}
          unexposedLabel={t("portfolio.unexposedLabel")}
          unexposedNote={t("portfolio.unexposedNote")}
          developingLabel={t("portfolio.developingLabel")}
          developedLabel={t("portfolio.developedLabel")}
          srNote={t("portfolio.srNote")}
          locale={locale}
          reduced={reduced}
        />
      </div>
    </SectionWrapper>
  );
}
