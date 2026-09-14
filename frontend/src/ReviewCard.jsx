import { useEffect, useId, useRef, useState } from "react";
import {
  WarningCircle,
  CheckCircle,
  CaretDown,
  ArrowSquareOut,
  Info,
} from "@phosphor-icons/react";

function AvailabilityInfo({ label, reason, alignRight }) {
  const [open, setOpen] = useState(false);
  const container = useRef(null);
  const helpId = useId();
  useEffect(() => {
    if (!open) return;
    const dismiss = (event) => {
      if (!container.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("focusin", dismiss);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("focusin", dismiss);
    };
  }, [open]);
  return (
    <div
      ref={container}
      className="relative"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          setOpen(false);
          event.currentTarget.querySelector("button").focus();
        }
      }}
    >
      <button
        type="button"
        aria-label={`Why is ${label} unavailable?`}
        aria-expanded={open}
        aria-controls={helpId}
        onClick={() => setOpen((value) => !value)}
        className="flex h-7 w-7 items-center justify-center rounded-full border-0 bg-transparent p-0 text-[#63736b]"
      >
        <Info size={18} aria-hidden="true" />
      </button>
      <p
        id={helpId}
        hidden={!open}
        className={`absolute bottom-full z-10 mb-2 w-[230px] rounded-lg border border-[#ccd8d1] bg-white p-3 text-left text-xs leading-relaxed text-[#34493e] shadow-md ${alignRight ? "-right-10" : "-left-10"}`}
      >
        {reason}
      </p>
    </div>
  );
}

/** Presentational HITL card. All authority and persistence stay with the host/API. */
export default function ReviewCard({
  systemId,
  action,
  headline,
  bullets = [],
  proceedRisk,
  holdRisk,
  proceedRisks = [],
  holdRisks = [],
  recommendation,
  explanation,
  canProceed = false,
  canHold = false,
  proceedUnavailableReason,
  holdUnavailableReason,
  initialReason = "",
  onReasonChange = () => {},
  onDecision,
  onRefresh,
  evidence,
  submission,
}) {
  const headingId = useId();
  const evidenceId = useId();
  const reasonRef = useRef(null);
  const detailsRef = useRef(null);
  const [choice, setChoice] = useState(null);
  const [reason, setReason] = useState(initialReason);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const Icon = recommendation === "yes" ? CheckCircle : WarningCircle;

  function inspect(event) {
    event.preventDefault();
    detailsRef.current.open = true;
    detailsRef.current.scrollIntoView?.({ behavior: "smooth", block: "start" });
    detailsRef.current.querySelector("summary").focus();
  }
  function choose(answer) {
    setChoice(answer);
    setError("");
    requestAnimationFrame(() => reasonRef.current?.focus());
  }
  async function save(event) {
    event.preventDefault();
    if (!reason.trim() || busy || (choice === "yes" ? !canProceed : !canHold))
      return;
    setBusy(true);
    setError("");
    try {
      await onDecision({ answer: choice, rationale: reason.trim() });
      setSaved(true);
    } catch (err) {
      setError(err.message || "The decision could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="reviewpoint-card mx-auto w-full max-w-[440px]">
      <article
        aria-labelledby={headingId}
        className="!mb-0 overflow-hidden rounded-2xl border border-solid border-[#ccd8d1] bg-white shadow-sm"
      >
        <header className="flex items-center justify-between gap-4 border-0 border-b border-solid border-[#e2e8e3] bg-transparent px-5 py-3.5">
          <a
            href={`#${evidenceId}`}
            onClick={inspect}
            title={`Inspect submission ${systemId}`}
            className="flex min-w-0 items-center gap-2 text-sm font-semibold text-[#225d4d] no-underline hover:underline"
          >
            <span className="truncate">{systemId}</span>
            <ArrowSquareOut size={15} aria-hidden="true" />
          </a>
        </header>
        <div className="px-5 pt-4 pb-5">
          <p className="mb-3 text-xs font-medium text-[#63736b]">{action}</p>
          <div className="flex min-h-[128px] items-start gap-3 pb-4">
            <Icon
              size={46}
              weight="fill"
              aria-hidden="true"
              className={
                recommendation === "yes" ? "text-[#337866]" : "text-[#c18a24]"
              }
            />
            <div className="min-w-0 flex-1 pt-0.5">
              <h2
                id={headingId}
                className="text-[21px] leading-[1.25] font-semibold tracking-[-0.025em]"
              >
                {headline}
              </h2>
              {bullets.length > 0 && (
                <ul className="mt-2 space-y-1 text-sm leading-relaxed text-[#52635a]">
                  {bullets.map((bullet, i) => (
                    <li key={i}>{bullet}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
          <div className="grid grid-cols-2 border-y border-solid border-[#e2e8e3] py-4">
            {[
              {
                answer: "yes",
                heading: "If you proceed",
                risks: proceedRisks,
                risk: proceedRisk,
                label: "Proceed",
                allowed: canProceed,
                unavailable: proceedUnavailableReason,
              },
              {
                answer: "no",
                heading: "If you hold",
                risks: holdRisks,
                risk: holdRisk,
                label: "Hold / fix",
                allowed: canHold,
                unavailable: holdUnavailableReason,
              },
            ].map((option, i) => (
              <div
                key={option.answer}
                className={`flex min-w-0 flex-col ${i ? "border-0 border-l border-solid border-[#e2e8e3] pl-4" : "pr-4"}`}
              >
                <h3 className="text-sm font-semibold text-[#263d33]">
                  {option.heading}
                </h3>
                <div className="mt-1.5 mb-4 flex-1 space-y-2 text-sm leading-snug text-[#52635a]">
                  {option.risks.length ? (
                    option.risks.map((risk) => (
                      <div key={risk.id}>
                        <p className="mb-1 text-[11px] font-medium text-[#63736b]">
                          Priority {risk.priority}
                        </p>
                        <p>{risk.consequence}</p>
                      </div>
                    ))
                  ) : (
                    <p>
                      {option.risk ||
                        "Consequences are not specified in this profile."}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  disabled={!option.allowed || busy || saved}
                  onClick={() => choose(option.answer)}
                  aria-pressed={choice === option.answer}
                  className={`w-full rounded-lg border px-1 py-2.5 text-sm font-semibold transition-colors ${
                    choice === option.answer
                      ? "border-[#225d4d] bg-[#225d4d] text-white"
                      : "border-[#aebfb4] bg-white text-[#225d4d] hover:bg-[#eef4ef]"
                  }`}
                >
                  {option.label}
                </button>
                <div className="mt-2 flex min-h-7 items-center justify-center gap-1 text-[11px] font-medium text-[#337866]">
                  {!option.allowed && option.unavailable && (
                    <AvailabilityInfo
                      label={option.label}
                      reason={option.unavailable}
                      alignRight={!!i}
                    />
                  )}
                  {recommendation === option.answer && (
                    <>
                      <CheckCircle size={14} weight="fill" aria-hidden="true" />
                      Recommended
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
          {choice && !saved && (
            <form onSubmit={save} className="block pt-4">
              <label className="block text-sm font-semibold">
                {choice === "yes" ? "Why proceed?" : "Why hold?"}
                <textarea
                  ref={reasonRef}
                  required
                  maxLength={4000}
                  value={reason}
                  onChange={(event) => {
                    setReason(event.target.value);
                    onReasonChange(event.target.value);
                  }}
                  placeholder="Your reason"
                  className="mt-2 min-h-20 w-full rounded-lg border border-solid border-[#aebfb4] p-2.5 text-sm font-normal"
                />
              </label>
              <p className="mt-2 text-xs text-[#63736b]">
                Records your decision. The host handles the action.
              </p>
              <div className="mt-3 flex gap-2">
                <button
                  type="submit"
                  disabled={!reason.trim() || busy}
                  className="rounded-lg border border-[#225d4d] bg-[#225d4d] px-3 py-2.5 text-sm font-semibold text-white"
                >
                  {busy
                    ? "Saving…"
                    : choice === "yes"
                      ? "Record proceed"
                      : "Record hold"}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setChoice(null)}
                  className="rounded-lg border border-[#ccd8d1] bg-white px-3 py-2.5 text-sm text-[#225d4d]"
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
          {error && (
            <div role="alert" className="mt-3 text-sm text-[#833c36]">
              {error}
              {onRefresh && (
                <button
                  type="button"
                  onClick={onRefresh}
                  className="mt-2 block rounded-lg border border-[#ccd8d1] bg-white px-3 py-2 text-sm text-[#225d4d]"
                >
                  Refresh review
                </button>
              )}
            </div>
          )}
          {saved && (
            <p
              role="status"
              className="mt-3 text-sm font-medium text-[#225d4d]"
            >
              Decision recorded. Host action has not been confirmed.
            </p>
          )}
          <div
            className={`pt-4 ${choice || saved ? "mt-4 border-t border-solid border-[#e2e8e3]" : ""}`}
          >
            <p className="text-sm leading-relaxed text-[#34493e]">
              {explanation}
            </p>
          </div>
        </div>
      </article>
      <details
        id={evidenceId}
        ref={detailsRef}
        className="mt-5 border-0 border-t border-solid border-[#ccd8d1] py-4"
      >
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-[#225d4d]">
          Inspect discrepancy
          <CaretDown size={17} aria-hidden="true" />
        </summary>
        <div className="mt-3 space-y-3 text-sm">
          <p>Retained submission and evidence for this review.</p>
          <pre className="max-h-96 overflow-auto rounded-lg bg-[#edf2ec] p-3 text-xs">
            {JSON.stringify({ submission, evidence }, null, 2)}
          </pre>
        </div>
      </details>
    </div>
  );
}
