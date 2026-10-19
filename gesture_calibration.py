"""Calibração guiada dos gestos: mede a sua mão em cada pose e grava limiares pessoais.

Lógica pura (sem câmera nem janela), para testar com mãos sintéticas. O runner fica em
gestures.py (`python gestures.py --calibrate`): ele abre a webcam, mostra as instruções que a
CalibrationSession devolve a cada quadro e, no fim, grava o resultado de calibrate() em
gestos_calibracao.json, que o Tuning.load() usa dali em diante.

Ideia: para cada medida que o classify usa (curva e alcance dos dedos, polegar, pinça), junta os
valores das poses em que ela deveria ser "baixa" e das em que deveria ser "alta" e põe o limiar no
vão entre as duas. Se as poses se sobrepõem (a medida não separa bem para você), aquele limiar
fica no padrão. No fim, reclassifica as amostras: se a calibração não acertar mais que o padrão,
nada muda.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from gesture_engine import (
    CALIBRATED_FIELDS,
    CALIBRATION_FILE,
    CALIBRATION_VERSION,
    Hand,
    Pose,
    Tuning,
    classify,
    hand_quality,
)

FOUR = ("index", "middle", "ring", "pinky")


@dataclass(frozen=True)
class Step:
    key: str
    pose: Pose
    title: str
    detail: str


STEPS = (
    Step("open", Pose.OPEN, "MAO ABERTA", "palma para a camera, dedos esticados e afastados"),
    Step("fist", Pose.FIST, "PUNHO", "feche a mao com o polegar por cima dos dedos"),
    Step("pinch", Pose.PINCH, "PINCA", "encoste o polegar na ponta do indicador, outros dedos abertos"),
    Step("point", Pose.POINT, "INDICADOR", "so o indicador esticado, os outros dobrados"),
    Step("two", Pose.TWO, "DOIS DEDOS", "indicador e medio esticados (V), os outros dobrados"),
    Step("thumb_down", Pose.THUMB_DOWN, "POLEGAR PARA BAIXO", "polegar apontando para baixo, dedos fechados"),
)


@dataclass(frozen=True)
class Prompt:
    title: str
    detail: str
    progress: float | None = None
    phase: str = "prepare"  # "prepare" | "record" | "done"
    step: int = 0  # passo atual (0-based) de len(STEPS)

    @property
    def done(self) -> bool:
        return self.phase == "done"


class CalibrationSession:
    """Walks through the poses: a countdown to get ready, then a few seconds of measuring.

    Call feed(t, hand) every frame (hand=None without a hand); it returns what to show. A step
    without enough good frames is repeated (up to `retries` times) and then skipped.
    """

    def __init__(
        self,
        steps: tuple[Step, ...] = STEPS,
        tuning: Tuning | None = None,
        prepare_s: float = 2.5,
        record_s: float = 2.0,
        settle_s: float = 0.3,
        min_samples: int = 15,
        retries: int = 2,
    ) -> None:
        self.steps = steps
        self.tuning = tuning or Tuning()
        self.prepare_s = prepare_s
        self.record_s = record_s
        self.settle_s = settle_s  # começo da gravação ignorado (a mão ainda está chegando na pose)
        self.min_samples = min_samples
        self.retries = retries
        self.samples: dict[str, list[Hand]] = {}
        self.skipped: list[str] = []
        self._index = 0
        self._phase = "prepare"
        self._since: float | None = None
        self._tries = 0
        self._current: list[Hand] = []
        self._note = ""

    @property
    def done(self) -> bool:
        return self._index >= len(self.steps)

    def feed(self, t: float, hand: Hand | None) -> Prompt:
        if self.done:
            return Prompt("CALIBRACAO CONCLUIDA", "", 1.0, "done", len(self.steps))
        if self._since is None:
            self._since = t
        step = self.steps[self._index]
        elapsed = t - self._since
        label = f"{self._index + 1}/{len(self.steps)} {step.title}"
        if self._phase == "prepare":
            if elapsed >= self.prepare_s:
                self._phase, self._since, self._current = "record", t, []
                return Prompt(label, "medindo... segure a pose", 0.0, "record", self._index)
            remaining = max(1, int(np.ceil(self.prepare_s - elapsed)))
            detail = f"{self._note}{step.detail} - comeca em {remaining}"
            return Prompt(label, detail, elapsed / self.prepare_s, "prepare", self._index)

        if elapsed >= self.settle_s and hand is not None and hand_quality(hand, self.tuning).ok:
            self._current.append(hand)
        if elapsed < self.record_s:
            return Prompt(label, f"medindo... segure a pose ({len(self._current)} quadros)", elapsed / self.record_s, "record", self._index)

        if len(self._current) >= self.min_samples:
            self.samples[step.key] = self._current
            self._advance(t, "")
        elif self._tries < self.retries:
            self._tries += 1
            self._phase, self._since = "prepare", t
            self._note = "nao vi sua mao direito, de novo: "
        else:
            self.skipped.append(step.key)
            self._advance(t, "")
        return self.feed(t, hand)

    def _advance(self, t: float, note: str) -> None:
        self._index += 1
        self._phase, self._since, self._tries, self._note = "prepare", t, 0, note
        self._current = []


# ───────────────────────── limiares ─────────────────────────


def _gap(low: list[float], high: list[float]) -> tuple[float, float] | None:
    """Gap between the values that should be low (their 95th percentile) and the high ones (5th)."""
    if not low or not high:
        return None
    top_of_low = float(np.percentile(low, 95))
    bottom_of_high = float(np.percentile(high, 5))
    return (top_of_low, bottom_of_high) if bottom_of_high > top_of_low else None


def _place(gap: tuple[float, float], default: float, k: float) -> float:
    """Threshold at fraction k of the gap; a default already inside it only moves halfway there.

    Poses held still for the calibration vary less than in real use, so a gap that the default
    already sits in is not a reason to tighten it to the edge of the measured values.
    """
    low, high = gap
    target = low + k * (high - low)
    if low < default < high:
        return default + 0.5 * (target - default)
    return target


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


EXTENDED = {"open": set(FOUR), "fist": set(), "point": {"index"}, "two": {"index", "middle"}}


def thresholds(samples: dict[str, list[Hand]], base: Tuning) -> tuple[dict[str, float], list[str]]:
    """Calibrated values (only the ones the samples could measure) and warnings."""
    metrics = {key: [classify(hand, base).metrics for hand in hands] for key, hands in samples.items()}
    out: dict[str, float] = {}
    warnings: list[str] = []

    def values(keys: tuple[str, ...], metric: str) -> list[float]:
        return [row[metric] for key in keys for row in metrics.get(key, [])]

    ext_bend: list[float] = []
    fold_bend: list[float] = []
    ext_reach: list[float] = []
    fold_reach: list[float] = []
    for key, extended in EXTENDED.items():
        for row in metrics.get(key, []):
            for finger in FOUR:
                (ext_bend if finger in extended else fold_bend).append(row[f"{finger}_bend"])
                (ext_reach if finger in extended else fold_reach).append(row[f"{finger}_reach"])
    gap = _gap(ext_bend, fold_bend)
    if gap:
        out["extend_bend"] = _clamp(_place(gap, base.extend_bend, 0.4), 35.0, 110.0)
        out["fold_bend"] = _clamp(_place(gap, base.fold_bend, 0.6), out["extend_bend"] + 5.0, 130.0)
    elif ext_bend and fold_bend:
        # Curvas sobrepostas (ex.: o mindinho de um punho frouxo curva tanto quanto um dedo aberto
        # que não estica de todo): o alcance separa os dois; a curva só precisa aceitar os abertos.
        needed = float(np.percentile(ext_bend, 95)) + 5.0
        if needed > base.extend_bend:
            out["extend_bend"] = _clamp(needed, 35.0, 110.0)
            out["fold_bend"] = _clamp(max(base.fold_bend, out["extend_bend"] + 5.0), 40.0, 130.0)
        warnings.append("a curva dos dedos abertos se parece com a do punho; quem separa é o alcance dos dedos")
    gap = _gap(fold_reach, ext_reach)
    if gap:
        out["fold_reach"] = _clamp(_place(gap, base.fold_reach, 0.4), 0.7, 1.3)
        out["extend_reach"] = _clamp(_place(gap, base.extend_reach, 0.6), out["fold_reach"] + 0.03, 1.5)
    elif ext_reach and fold_reach:
        warnings.append("o alcance dos dedos não separou mão aberta de punho; mantive o padrão")

    gap = _gap(values(("fist",), "thumb_out"), values(("open", "thumb_down"), "thumb_out"))
    if gap:
        out["thumb_fold_out"] = _clamp(_place(gap, base.thumb_fold_out, 0.3), 0.2, 0.9)
        out["thumb_extend_out"] = _clamp(_place(gap, base.thumb_extend_out, 0.6), out["thumb_fold_out"] + 0.05, 1.5)
    thumb_bend = values(("open", "thumb_down"), "thumb_bend")
    if thumb_bend:
        needed = float(np.percentile(thumb_bend, 95)) + 10.0
        out["thumb_extend_bend"] = _clamp(max(base.thumb_extend_bend, needed), 30.0, 60.0)

    gap = _gap(values(("pinch",), "pinch"), values(("open", "point", "two"), "pinch"))
    if gap:
        out["pinch_on"] = _clamp(_place(gap, base.pinch_on, 0.4), 0.12, 0.6)
        out["pinch_pose"] = _clamp(_place(gap, base.pinch_pose, 0.4), 0.12, 0.6)
        out["closing_pinch"] = _clamp(_place(gap, base.closing_pinch, 0.55), out["pinch_on"] + 0.03, 0.9)
        out["pinch_off"] = _clamp(_place(gap, base.pinch_off, 0.75), out["closing_pinch"] + 0.03, 1.0)
    elif values(("pinch",), "pinch"):
        warnings.append("a pinça não se separou das outras poses; mantive o padrão")

    down = values(("thumb_down",), "thumb_down")
    if down:
        gap = _gap(values(("fist",), "thumb_down"), down) or (0.0, float(np.percentile(down, 5)))
        out["thumb_down_min"] = _clamp(_place(gap, base.thumb_down_min, 0.5), 0.12, 0.8)
    curled = values(("thumb_down",), "curl")
    if curled:
        gap = _gap(values(("open",), "curl"), curled) or (0.0, float(np.percentile(curled, 5)) - 5.0)
        out["thumb_down_curl"] = _clamp(_place(gap, base.thumb_down_curl, 0.5), 25.0, 80.0)

    palms = [row["palm"] for rows in metrics.values() for row in rows]
    if palms:
        out["reference_palm"] = _clamp(float(np.median(palms)), 0.05, 0.6)
    return out, warnings


def accuracy(samples: dict[str, list[Hand]], tuning: Tuning, steps: tuple[Step, ...] = STEPS) -> dict[str, float]:
    """Fraction of the frames of each pose that classify() recognizes as that pose."""
    expected = {step.key: step.pose for step in steps}
    result = {}
    for key, hands in samples.items():
        if key in expected and hands:
            hits = sum(classify(hand, tuning).pose == expected[key] for hand in hands)
            result[key] = round(hits / len(hands), 3)
    return result


def calibrate(samples: dict[str, list[Hand]], base: Tuning | None = None) -> tuple[Tuning, dict[str, Any]]:
    """Personal Tuning from the measured poses, plus a report (accuracy before/after, changes)."""
    base = base or Tuning()
    values, warnings = thresholds(samples, base)
    tuned = replace(base, **values)
    before, after = accuracy(samples, base), accuracy(samples, tuned)
    mean_before = float(np.mean(list(before.values()))) if before else 0.0
    mean_after = float(np.mean(list(after.values()))) if after else 0.0
    if after and mean_after + 1e-9 < mean_before:
        warnings.append("os limiares medidos acertaram menos que os padrão; mantive o padrão")
        tuned, values, after = base, {}, before
    report = {
        "samples": {key: len(hands) for key, hands in samples.items()},
        "accuracy_before": before,
        "accuracy_after": after,
        "changed": {name: [round(getattr(base, name), 3), round(value, 3)] for name, value in values.items()},
        "warnings": warnings,
    }
    return tuned, report


def save(tuning: Tuning, report: dict[str, Any], path: Path | str | None = None) -> Path:
    """Write the calibrated fields to gestos_calibracao.json (atomic replace)."""
    path = Path(path) if path is not None else CALIBRATION_FILE
    data = {
        "version": CALIBRATION_VERSION,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tuning": {name: round(float(getattr(tuning, name)), 4) for name in CALIBRATED_FIELDS},
        "report": report,
    }
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return path


def summary(report: dict[str, Any]) -> list[str]:
    """Report as short lines for the terminal (Portuguese, user-facing)."""
    lines = []
    for key, value in report.get("accuracy_after", {}).items():
        before = report.get("accuracy_before", {}).get(key)
        lines.append(f"  {key:<11} acerto {before:.0%} → {value:.0%}" if before is not None else f"  {key:<11} {value:.0%}")
    for name, (old, new) in report.get("changed", {}).items():
        lines.append(f"  {name}: {old} → {new}")
    lines.extend(f"  aviso: {warning}" for warning in report.get("warnings", []))
    return lines

