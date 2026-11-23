/**
 * How a QC stage is done, as the screens name it: a batch record (steps, check points and
 * sign-off columns), tested in the lab (samples and a certificate), or passed / failed by QA.
 */
export type StageMode = "RECORD" | "TESTED" | "QA";

/**
 * Kinds of stage the screens do not offer for now, at the lab's request (19-Nov-2026): a new
 * stage is a batch record. Stages already saved as lab-tested or QA pass / fail are left as
 * they are — they keep showing, keep their kind when the stages are saved again, and their
 * samples are still registered and tested. To offer a kind again, take it out of this list.
 */
const HIDDEN: ReadonlySet<StageMode> = new Set<StageMode>(["TESTED", "QA"]);

export const modeShown = (mode: StageMode): boolean => mode === "RECORD" || !HIDDEN.has(mode);

/** A saved stage's mode: lab-tested, a batch record (it has sign-off columns), or QA pass / fail. */
export function modeOfStage(kind: string, signoffs: number): StageMode {
  return kind === "TESTED" ? "TESTED" : signoffs ? "RECORD" : "QA";
}
