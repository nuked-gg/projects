#!/usr/bin/env python3
"""
WAVE CHALLENGE
==============
An endless, Geometry Dash-style wave game.

Hold W, SPACE or UP / arrow to fly diagonally up. Release to fly down.
Thread an endless neon obstacle course full of spikes, blocks and gates.
The cave twists and tightens, portals change your speed, and mini portals
swap in a smaller, steeper, momentum-driven wave.

Run with:  python3 game.py
"""

from __future__ import annotations

import math
import os
import random
import sys
from bisect import bisect_right
from collections import deque

import pygame

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

WIDTH, HEIGHT = 1280, 720
FPS = 120
PLAYER_SCREEN_X = 300
BASE_SPEED = 300.0
SPEED_TIERS = (1.0, 1.28, 1.6, 1.95, 2.35)
MAX_TIER = len(SPEED_TIERS) - 1

# Corridor / obstacle geometry
BAR = 8.0                 # world px per wall column
DIFFICULTY_DISTANCE = 40000.0
NORMAL_SLOPE = 0.9
MINI_SLOPE = 1.12         # mini wave is steeper...
MINI_TURN_TAU = 0.085     # ...and carries momentum when changing direction
SPIKE_W = 26.0
SPIKE_H = 29.0
CLEAR_SINGLE = 104.0      # required free space past one-sided obstacles
CLEAR_GATE = 98.0         # required free space through gates

# Palette
BG_TOP = (7, 10, 22)
BG_BOTTOM = (18, 12, 36)
WALL_FILL = (11, 18, 34)
WALL_LINE = (24, 42, 72)
TEXT = (232, 242, 255)
MUTED = (124, 143, 175)
ACCENTS = (
    (0, 226, 255),
    (74, 255, 196),
    (255, 214, 92),
    (255, 118, 214),
    (255, 92, 118),
)
MINI_COLOR = (255, 140, 235)
RED = (255, 84, 104)
GOLD = (255, 214, 92)
GREEN = (116, 255, 168)

SAVE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "highscore.txt")
KEY_CAP = (26, 34, 52)
KEY_CAP_EDGE = (58, 76, 108)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def clamp(value, low, high):
    return low if value < low else high if value > high else value


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(t):
    t = clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def blend(c1, c2, t):
    t = clamp(t, 0.0, 1.0)
    return (
        int(lerp(c1[0], c2[0], t)),
        int(lerp(c1[1], c2[1], t)),
        int(lerp(c1[2], c2[2], t)),
    )


def load_best() -> int:
    try:
        with open(SAVE_PATH, "r", encoding="utf-8") as fh:
            return max(0, int(fh.read().strip() or 0))
    except (OSError, ValueError):
        return 0


def save_best(value: int) -> None:
    try:
        with open(SAVE_PATH, "w", encoding="utf-8") as fh:
            fh.write(str(int(value)))
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Endless corridor
# --------------------------------------------------------------------------- #

class Corridor:
    """Endless cave plus hand-built-feeling spike/block structures.

    A random-walk of waypoints is joined with cosine interpolation for the
    tunnel walls.  Inside the tunnel, the generator drops spikes, blocks,
    staircases and gates, always leaving a threadable opening behind.
    Gap width and obstacle frequency both ramp up with distance.
    """

    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        start_y = HEIGHT * 0.52
        self.pts = [(-700.0, start_y), (0.0, start_y)]
        self.ends = [0.0]                      # ends[i] = x of pts[i + 1]
        self._next_x = 0.0
        self._next_y = start_y

        self.bars: dict[int, tuple[int, int]] = {}
        self.portals: list[dict] = []
        self.obstacles: list[dict] = []
        self._next_portal_x = 1050.0
        self._next_obstacle_x = 820.0
        self._portal_count = 0
        self._speed_plan = 1
        self._mode_plan = "mini"

        while self.ends[-1] < 2400.0:
            self._add_point()
        while self._next_portal_x < 1600.0:
            self._add_portal()

    # -- path -------------------------------------------------------------- #

    def difficulty(self, x: float) -> float:
        return smoothstep(clamp(x / DIFFICULTY_DISTANCE, 0.0, 1.0))

    def _add_point(self) -> None:
        d = self.difficulty(self._next_x)
        spacing = lerp(350.0, 195.0, d) * self.rng.uniform(0.85, 1.15)
        amp = spacing * lerp(0.16, 0.36, d) * self.rng.uniform(0.55, 1.0)
        if self.rng.random() < 0.5:
            amp = -amp
        new_y = clamp(self._next_y + amp, 190.0, 530.0)
        new_x = self._next_x + spacing
        self.pts.append((new_x, new_y))
        self.ends.append(new_x)
        self._next_x = new_x
        self._next_y = new_y

    def _ensure_points(self, x: float) -> None:
        while self.ends[-1] < x + 700.0:
            self._add_point()

    def ensure(self, x: float) -> None:
        self._ensure_points(x)
        while self._next_obstacle_x < x + 760.0:
            self._add_obstacle()
        while self._next_portal_x < x + 460.0:
            self._add_portal()

    def center_at(self, x: float) -> float:
        self._ensure_points(x)
        i = bisect_right(self.ends, x)
        i = min(i, len(self.ends) - 1)
        x0, y0 = self.pts[i]
        x1, y1 = self.pts[i + 1]
        t = clamp((x - x0) / (x1 - x0), 0.0, 1.0)
        u = 0.5 - 0.5 * math.cos(math.pi * t)
        return y0 + (y1 - y0) * u

    def gap_at(self, x: float) -> float:
        d = self.difficulty(x)
        gap = lerp(300.0, 205.0, d) + 11.0 * math.sin(x * 0.0016) + 7.0 * math.sin(x * 0.0041 + 1.3)
        return max(196.0, gap)

    def bounds_at(self, x: float) -> tuple[float, float]:
        c = self.center_at(x)
        g = self.gap_at(x)
        return c - g * 0.5, c + g * 0.5

    # -- collision columns ------------------------------------------------- #

    def bar(self, index: int) -> tuple[int, int]:
        """Return (ceiling, floor) for wall column ``index``."""
        cached = self.bars.get(index)
        if cached is not None:
            return cached
        x = (index + 0.5) * BAR
        c = self.center_at(x)
        g = self.gap_at(x)
        ceil_y = int((c - g * 0.5) // BAR * BAR)
        floor_y = int(math.ceil((c + g * 0.5) / BAR) * BAR)
        result = (ceil_y, floor_y)
        self.bars[index] = result
        return result

    def prune(self, camera_x: float) -> None:
        cut = int((camera_x - 400.0) // BAR)
        stale = [k for k in self.bars if k < cut]
        for k in stale:
            del self.bars[k]

        boundary = camera_x - 600.0
        while self.obstacles and self.obstacles[0]["x1"] < boundary:
            self.obstacles.pop(0)
        self.portals = [p for p in self.portals if not p["done"] or p["x"] > boundary]

    # -- obstacle generation ----------------------------------------------- #

    def _span_stats(self, x0: float, x1: float) -> tuple[float, float, float, float]:
        """Conservative (ceil_top, ceil_bottom, floor_top, floor_bottom)."""
        x0 -= 6.0
        x1 += 6.0
        n = max(3, int((x1 - x0) / 9.0) + 1)
        ceil_top = floor_top = 1e9
        ceil_bottom = floor_bottom = -1e9
        for i in range(n + 1):
            x = x0 + (x1 - x0) * i / n
            c = self.center_at(x)
            g = self.gap_at(x)
            ceiling = c - g * 0.5
            floor = c + g * 0.5
            ceil_top = min(ceil_top, ceiling)
            ceil_bottom = max(ceil_bottom, ceiling)
            floor_top = min(floor_top, floor)
            floor_bottom = max(floor_bottom, floor)
        return ceil_top, ceil_bottom, floor_top, floor_bottom

    @staticmethod
    def _finish(kind: str, x0: float, x1: float, rects, spikes, safe_lo, safe_hi) -> dict:
        return {
            "kind": kind,
            "x0": float(x0),
            "x1": float(x1),
            "rects": rects,
            "spikes": spikes,
            "safe_lo": float(safe_lo),
            "safe_hi": float(safe_hi),
        }

    def _obstacle_spikes(self, x: float, d: float, ceiling: bool):
        count = 1
        if self.rng.random() < 0.45 + 0.35 * d:
            count += 1
        if self.rng.random() < 0.12 + 0.45 * d:
            count += 1
        if self.rng.random() < 0.04 + 0.24 * d:
            count += 1
        count = min(count, 4)
        want_h = self.rng.uniform(SPIKE_H - 5.0, SPIKE_H + 3.0)
        spikes = []
        apexes = []

        for i in range(count):
            sx = x + i * (SPIKE_W + 2.0)
            cx = sx + SPIKE_W * 0.5
            _ct, cb, ft, _fb = self._span_stats(sx, sx + SPIKE_W)
            c = self.center_at(cx)
            g = self.gap_at(cx)
            if ceiling:
                base = c - g * 0.5 - 10.0
                limit = ft - base - CLEAR_SINGLE
            else:
                base = c + g * 0.5 + 10.0
                limit = base - cb - CLEAR_SINGLE
            height = min(want_h, limit)
            if height < 16.0:
                return None
            if ceiling:
                spikes.append((sx, base, SPIKE_W, height, "down"))
                apexes.append(base + height)
            else:
                spikes.append((sx, base - height, SPIKE_W, height, "up"))
                apexes.append(base - height)

        x1 = x + count * (SPIKE_W + 2.0) - 2.0
        _ct2, cb2, ft2, _fb2 = self._span_stats(x, x1)
        if ceiling:
            safe_lo = max(apexes) + 12.0
            safe_hi = ft2 - 12.0
            kind = "ceil_spikes"
        else:
            safe_lo = cb2 + 12.0
            safe_hi = min(apexes) - 12.0
            kind = "spikes"
        if safe_hi - safe_lo < 34.0:
            return None
        return self._finish(kind, x, x1, [], spikes, safe_lo, safe_hi)

    def _obstacle_block(self, x: float, d: float, ceiling: bool):
        w = self.rng.uniform(38.0, 66.0) + 22.0 * d
        _ct, cb, ft, fb = self._span_stats(x, x + w)
        max_total = ft - cb - CLEAR_SINGLE
        if max_total < 34.0:
            return None

        want_spikes = w > 36.0 and self.rng.random() < 0.22 + 0.48 * d
        spike_count = 0
        if want_spikes:
            spike_count = 1
            if w > 58.0 and self.rng.random() < 0.35:
                spike_count = 2
            spike_count = min(spike_count, max(1, int(w // 30.0)))

        spike_extra = SPIKE_H if spike_count else 0.0
        max_block = max_total - spike_extra
        if max_block < 22.0:
            spike_count = 0
            spike_extra = 0.0
            max_block = max_total
        if max_block < 22.0:
            return None

        desired = self.rng.uniform(42.0, 76.0) + 32.0 * d
        block_h = clamp(desired, 22.0, max_block)

        if ceiling:
            total = block_h + spike_extra
            if total > max_total:
                block_h = max_total - spike_extra
                total = max_total
            bottom = _ct + total
            top = _ct - 14.0
            rect = (x, top, w, bottom - top)
            spikes = []
            for i in range(spike_count):
                cx = x + w * (i + 1) / (spike_count + 1)
                sx = cx - SPIKE_W * 0.5
                base = bottom - 2.0
                spikes.append((sx, base, SPIKE_W, SPIKE_H, "down"))
            apex = bottom + (SPIKE_H if spike_count else 0.0)
            safe_lo = max(apex, cb) + 12.0
            safe_hi = ft - 12.0
            kind = "hang_block"
        else:
            total = block_h + spike_extra
            if total > max_total:
                block_h = max_total - spike_extra
                total = max_total
            block_top = ft - block_h
            apex = block_top - (SPIKE_H if spike_count else 0.0)
            rect = (x, block_top, w, fb + 14.0 - block_top)
            spikes = []
            for i in range(spike_count):
                cx = x + w * (i + 1) / (spike_count + 1)
                sx = cx - SPIKE_W * 0.5
                spikes.append((sx, block_top - SPIKE_H, SPIKE_W, SPIKE_H, "up"))
            safe_lo = cb + 12.0
            safe_hi = apex - 12.0
            kind = "block"

        if safe_hi - safe_lo < 34.0:
            return None
        return self._finish(kind, x, x + w, [rect], spikes, safe_lo, safe_hi)

    def _obstacle_stairs(self, x: float, d: float):
        steps = 2 if self.rng.random() < 0.55 else 3
        w = self.rng.uniform(40.0, 52.0)
        rise = self.rng.uniform(16.0, 24.0) * (0.8 + 0.6 * d)
        first = self.rng.uniform(28.0, 38.0)

        _ct, cb, ft, _fb = self._span_stats(x, x + steps * (w - 2.0))
        tallest = None
        for i in range(steps):
            h = first + rise * i
            if tallest is None or h > tallest:
                tallest = h
        spike_on_top = self.rng.random() < 0.25 + 0.45 * d
        total = (tallest or 0.0) + (SPIKE_H if spike_on_top else 0.0)
        max_total = ft - cb - CLEAR_SINGLE
        if total > max_total:
            spike_on_top = False
            total = tallest or 0.0
        if total > max_total:
            scale = max_total / max(1.0, total)
            rise *= max(0.0, scale)
            first *= max(0.0, scale)
            tallest = first + rise * (steps - 1)
            spike_on_top = False
            total = tallest
        if total < 24.0 or total > max_total:
            return None

        rects = []
        spikes = []
        for i in range(steps):
            sx = x + i * (w - 2.0)
            top_h = first + rise * i
            _c1, _c2, _f1, f2 = self._span_stats(sx, sx + w)
            top = ft - top_h
            rects.append((sx, top, w, f2 + 14.0 - top))
            if spike_on_top and i == steps - 1:
                cx = sx + w * 0.5
                spikes.append((cx - SPIKE_W * 0.5, top - SPIKE_H, SPIKE_W, SPIKE_H, "up"))

        apex = ft - total
        safe_lo = cb + 12.0
        safe_hi = apex - 12.0
        if safe_hi - safe_lo < 34.0:
            return None
        return self._finish("stairs", x, x + steps * (w - 2.0) - 2.0, rects, spikes, safe_lo, safe_hi)

    def _obstacle_gate(self, x: float, d: float):
        w = self.rng.uniform(58.0, 88.0)
        ct, cb, ft, fb = self._span_stats(x, x + w)
        max_total = ft - cb - CLEAR_GATE
        if max_total < 34.0:
            return None
        total = min(self.rng.uniform(46.0, 84.0), max_total)
        split = self.rng.uniform(0.35, 0.65)
        h_floor = max(12.0, total * split)
        h_ceil = max(12.0, total - h_floor)

        top = ft - h_floor
        bottom = ct + h_ceil
        if top - max(bottom, cb) < CLEAR_GATE:
            h_floor *= 0.8
            h_ceil *= 0.8
            top = ft - h_floor
            bottom = ct + h_ceil

        spikes = []
        spike_on_top = False
        if w > 52.0 and self.rng.random() < 0.30 + 0.5 * d:
            if (top - SPIKE_H) - (bottom + SPIKE_H) >= CLEAR_GATE + 6.0:
                spike_on_top = True
                cx = x + w * 0.5
                spikes.append((cx - SPIKE_W * 0.5, top - SPIKE_H, SPIKE_W, SPIKE_H, "up"))
                spikes.append((cx - SPIKE_W * 0.5, bottom, SPIKE_W, SPIKE_H, "down"))

        if top - max(bottom, cb) < 30.0:
            return None

        rects = [
            (x, top, w, fb + 14.0 - top),
            (x, ct - 14.0, w, bottom - (ct - 14.0)),
        ]
        safe_lo = max(bottom, cb) + 12.0
        safe_hi = top - 12.0
        if spike_on_top:
            safe_lo += SPIKE_H
            safe_hi -= SPIKE_H
        if safe_hi - safe_lo < 30.0:
            return None
        return self._finish("gate", x, x + w, rects, spikes, safe_lo, safe_hi)

    def _obstacle_spike_gate(self, x: float, d: float):
        count = 1 if self.rng.random() < 0.65 else 2
        width = count * SPIKE_W + (count - 1) * 2.0
        ct, cb, ft, fb = self._span_stats(x, x + width)
        want_h = self.rng.uniform(SPIKE_H - 6.0, SPIKE_H + 1.0)
        h = want_h
        for _ in range(4):
            floor_base = fb + 10.0
            ceil_base = ct - 10.0
            floor_apex = floor_base - h
            ceil_apex = ceil_base + h
            if floor_apex - ceil_apex >= CLEAR_GATE:
                break
            h *= 0.82
        else:
            return None
        if h < 16.0:
            return None

        spikes = []
        for i in range(count):
            sx = x + i * (SPIKE_W + 2.0)
            cx = sx + SPIKE_W * 0.5
            c = self.center_at(cx)
            g = self.gap_at(cx)
            spikes.append((sx, c + g * 0.5 + 10.0 - h, SPIKE_W, h, "up"))
            spikes.append((sx, c - g * 0.5 - 10.0, SPIKE_W, h, "down"))

        safe_lo = max(sp[1] + sp[3] for sp in spikes if sp[4] == "down") + 12.0
        safe_hi = min(sp[1] for sp in spikes if sp[4] == "up") - 12.0
        if safe_hi - safe_lo < 30.0:
            return None
        return self._finish("spike_gate", x, x + width, [], spikes, safe_lo, safe_hi)

    def _build_obstacle(self, x: float, d: float):
        kinds = ("spikes", "ceil_spikes", "block", "hang_block", "stairs", "gate", "spike_gate")
        weights = (
            24.0,
            14.0 + 10.0 * d,
            22.0,
            16.0 + 8.0 * d,
            4.0 + 14.0 * d,
            3.0 + 15.0 * d,
            4.0 + 15.0 * d,
        )
        kind = self.rng.choices(kinds, weights=weights, k=1)[0]
        if kind == "spikes":
            return self._obstacle_spikes(x, d, False)
        if kind == "ceil_spikes":
            return self._obstacle_spikes(x, d, True)
        if kind == "block":
            return self._obstacle_block(x, d, False)
        if kind == "hang_block":
            return self._obstacle_block(x, d, True)
        if kind == "stairs":
            return self._obstacle_stairs(x, d)
        if kind == "gate":
            return self._obstacle_gate(x, d)
        return self._obstacle_spike_gate(x, d)

    def _add_obstacle(self) -> None:
        start = max(760.0, self._next_obstacle_x)

        d = self.difficulty(start)
        for attempt in range(4):
            x = start + attempt * 95.0
            if any(
                not portal["done"] and portal["x"] - 255.0 < x < portal["x"] + 255.0
                for portal in self.portals
            ):
                continue
            for _ in range(3):
                obstacle = self._build_obstacle(x, d)
                if obstacle is not None:
                    self.obstacles.append(obstacle)
                    spacing = lerp(980.0, 540.0, d) * self.rng.uniform(0.88, 1.15)
                    self._next_obstacle_x = obstacle["x1"] + spacing
                    return
        next_portal = next(
            (p for p in self.portals if not p["done"] and p["x"] > start - 255.0), None
        )
        if next_portal is not None and next_portal["x"] < start + 500.0:
            self._next_obstacle_x = next_portal["x"] + 310.0
        else:
            self._next_obstacle_x = start + 340.0

    # -- portals ----------------------------------------------------------- #

    def _add_portal(self) -> None:
        x = self._next_portal_x
        for _ in range(6):
            conflict = [
                ob for ob in self.obstacles if ob["x1"] > x - 230.0 and ob["x0"] < x + 230.0
            ]
            if not conflict:
                break
            x = max(ob["x1"] for ob in conflict) + 250.0

        if self._portal_count % 4 in (0, 2):
            kind = "speed"
            tier = self._speed_plan
            self._speed_plan = 2 if self._speed_plan >= MAX_TIER else self._speed_plan + 1
        else:
            kind = self._mode_plan
            self._mode_plan = "normal" if kind == "mini" else "mini"
            tier = 0
        self.portals.append({"x": x, "kind": kind, "tier": tier, "done": False})
        self._portal_count += 1
        self._next_portal_x = x + self.rng.uniform(1300.0, 1800.0)


# --------------------------------------------------------------------------- #
# Particles
# --------------------------------------------------------------------------- #

class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "size", "color", "gravity")

    def __init__(self, x, y, vx, vy, life, size, color, gravity=0.0):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life
        self.size = size
        self.color = color
        self.gravity = gravity


# --------------------------------------------------------------------------- #
# Game
# --------------------------------------------------------------------------- #

class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Wave Challenge")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self._set_window_icon()

        self.fonts: dict[tuple[int, bool], pygame.font.Font] = {}
        self.bg = self._make_background()
        self.stars = [
            {
                "x": random.uniform(0.0, WIDTH),
                "y": random.uniform(0.0, HEIGHT),
                "r": random.choice((1, 1, 1, 2, 2, 3)),
                "p": random.uniform(0.05, 0.35),
                "phase": random.uniform(0.0, math.tau),
            }
            for _ in range(130)
        ]

        self.best = load_best()
        self.state = "menu"
        self.t = 0.0
        self.dead_timer = 0.0
        self.run_time = 0.0
        self.shake = 0.0
        self.shake_x = 0.0
        self.shake_y = 0.0
        self.toasts: list[dict] = []
        self.particles: list[Particle] = []
        self.trail: deque[tuple[float, float]] = deque()
        self.running = True
        self._emit_accum = 0.0

        # Filled in by new_run()
        self.corridor = Corridor(random.randrange(1, 10**6))
        self.player_x = 0.0
        self.player_y = HEIGHT * 0.5
        self.camera_x = self.player_x - PLAYER_SCREEN_X
        self.tier = 0
        self.mini = False
        self.distance = 0
        self.speed = BASE_SPEED
        self.held = False
        self.mini_vy = 1.0

    # -- setup ------------------------------------------------------------- #

    def _set_window_icon(self) -> None:
        icon = pygame.Surface((32, 32), pygame.SRCALPHA)
        pygame.draw.polygon(icon, ACCENTS[0], [(26, 16), (6, 4), (11, 16), (6, 28)])
        pygame.display.set_icon(icon)

    def _make_background(self) -> pygame.Surface:
        surf = pygame.Surface((WIDTH, HEIGHT))
        for y in range(HEIGHT):
            t = y / (HEIGHT - 1)
            color = blend(BG_TOP, BG_BOTTOM, t)
            pygame.draw.line(surf, color, (0, y), (WIDTH, y))
        glow = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        pygame.draw.circle(glow, (50, 40, 110, 42), (WIDTH // 2, HEIGHT // 2), 520)
        surf.blit(glow, (0, 0))
        return surf

    def font(self, size: int, bold: bool = False) -> pygame.font.Font:
        key = (size, bold)
        f = self.fonts.get(key)
        if f is None:
            f = pygame.font.SysFont(
                "Segoe UI, SF Pro Display, Helvetica, Arial, DejaVu Sans", size, bold=bold
            )
            self.fonts[key] = f
        return f

    # -- run --------------------------------------------------------------- #

    def new_run(self) -> None:
        self.corridor = Corridor(random.randrange(1, 10**6))
        self.player_x = 0.0
        self.player_y = self.corridor.center_at(0.0)
        self.camera_x = self.player_x - PLAYER_SCREEN_X
        self.tier = 0
        self.mini = False
        self.distance = 0
        self.speed = BASE_SPEED
        self.trail.clear()
        self.particles.clear()
        self.toasts.clear()
        self.shake = 0.0
        self.shake_x = 0.0
        self.shake_y = 0.0
        self._emit_accum = 0.0
        self.dead_timer = 0.0
        self.run_time = 0.0
        self.mini_vy = 1.0
        self.state = "playing"

    @property
    def radius(self) -> float:
        return 4.2 if self.mini else 6.6

    @property
    def slope(self) -> float:
        """Signed screen-space slope, used to point the wave icon."""
        if self.mini:
            return self.mini_vy * MINI_SLOPE
        return (-NORMAL_SLOPE if self.held else NORMAL_SLOPE)

    @property
    def accent(self) -> tuple[int, int, int]:
        color = ACCENTS[self.tier]
        if self.mini:
            color = blend(color, MINI_COLOR, 0.35)
        return color

    # -- events ------------------------------------------------------------ #

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
            return

        if event.type != pygame.KEYDOWN:
            return

        key = event.key
        if key in (pygame.K_ESCAPE, pygame.K_p):
            if self.state == "playing":
                self.state = "paused"
            elif self.state == "paused":
                self.state = "playing"
            elif self.state == "dead":
                self.best = max(self.best, self.distance)
                save_best(self.best)
                self.state = "menu"
            return

        start_keys = (
            pygame.K_SPACE,
            pygame.K_RETURN,
            pygame.K_w,
            pygame.K_UP,
            pygame.K_KP_ENTER,
        )
        if self.state == "menu" and key in start_keys:
            self.new_run()
        elif self.state == "dead" and (
            key == pygame.K_r or (self.dead_timer > 0.35 and key in start_keys)
        ):
            self.new_run()
        elif self.state == "paused" and key in (pygame.K_r,):
            self.new_run()
        elif self.state == "playing" and key == pygame.K_r:
            self.new_run()

    # -- simulation -------------------------------------------------------- #

    def update(self, dt: float, held: bool) -> None:
        dt = min(dt, 1.0 / 30.0)
        self.t += dt
        self.held = held and self.state == "playing"

        # Timers / visuals that keep ticking in every state.
        for toast in self.toasts:
            toast["life"] -= dt
        self.toasts = [t for t in self.toasts if t["life"] > 0.0]

        if self.shake > 0.0:
            self.shake = max(0.0, self.shake - dt * 42.0)
            self.shake_x = random.uniform(-self.shake, self.shake)
            self.shake_y = random.uniform(-self.shake, self.shake)
        else:
            self.shake_x = 0.0
            self.shake_y = 0.0

        if self.state == "playing":
            self._update_playing(dt)
        elif self.state == "dead":
            self.dead_timer += dt

        self._update_particles(dt)

    def _update_playing(self, dt: float) -> None:
        self.run_time += dt
        self.speed = BASE_SPEED * SPEED_TIERS[self.tier]
        target_dir = -1.0 if self.held else 1.0
        if self.mini:
            # Mini wave steers toward the held direction with momentum, so
            # reversals carve curves instead of snapping instantly.
            blend_k = 1.0 - math.exp(-dt / MINI_TURN_TAU)
            self.mini_vy += (target_dir - self.mini_vy) * blend_k
            move_dir = self.mini_vy
            slope = MINI_SLOPE
        else:
            self.mini_vy = target_dir
            move_dir = target_dir
            slope = NORMAL_SLOPE

        dx = self.speed * dt
        dy = move_dir * self.speed * slope * dt
        self.corridor.ensure(self.player_x + WIDTH + 600.0)

        steps = max(1, int(math.ceil(abs(dx) / 3.0)))
        step_x = dx / steps
        step_y = dy / steps
        died = False
        for _ in range(steps):
            self.player_x += step_x
            self.player_y += step_y
            if self._collides(self.player_x, self.player_y):
                died = True
                break
        self.player_y = clamp(self.player_y, -80.0, HEIGHT + 80.0)

        # Portals
        for portal in self.corridor.portals:
            if portal["done"] or self.player_x < portal["x"]:
                continue
            portal["done"] = True
            self._apply_portal(portal)

        self.camera_x = self.player_x - PLAYER_SCREEN_X
        self.distance = max(0, int(self.player_x / 10.0))

        if died:
            self._die()
            return

        # Trail and sparks
        self.trail.append((self.player_x, self.player_y))
        while len(self.trail) > 200 or (
            len(self.trail) > 2 and self.trail[-1][0] - self.trail[0][0] > 330.0
        ):
            self.trail.popleft()

        self._emit_accum += dt
        interval = 0.018
        while self._emit_accum >= interval:
            self._emit_accum -= interval
            self._spawn_trail_spark()

        self.corridor.prune(self.camera_x)

    def _apply_portal(self, portal: dict) -> None:
        kind = portal["kind"]
        if kind == "speed":
            self.tier = int(portal["tier"])
            mult = SPEED_TIERS[self.tier]
            label = "SPEED UP" if self.tier > 0 else "SPEED"
            self.toast(f"{label}  {mult:.2f}x", ACCENTS[self.tier])
        elif kind == "mini":
            self.mini = True
            self.mini_vy = -1.0 if self.held else 1.0
            self.toast("MINI WAVE  \u2022  FLOATY PHYSICS", MINI_COLOR)
        else:
            self.mini = False
            self.mini_vy = -1.0 if self.held else 1.0
            self.toast("NORMAL WAVE", ACCENTS[0])

    def _collides(self, x: float, y: float) -> bool:
        r = self.radius
        first = int(math.floor((x - r) / BAR))
        last = int(math.floor((x + r) / BAR))
        r2 = r * r
        for i in range(first, last + 1):
            ceil_y, floor_y = self.corridor.bar(i)
            bx = i * BAR
            nx = clamp(x, bx, bx + BAR)
            # Top wall (everything above the ceiling).
            if y - r < ceil_y:
                ny = ceil_y
                if (x - nx) ** 2 + (y - ny) ** 2 < r2:
                    return True
            # Bottom wall (everything below the floor).
            if y + r > floor_y:
                ny = floor_y
                if (x - nx) ** 2 + (y - ny) ** 2 < r2:
                    return True
        return self._collides_obstacles(x, y)

    @staticmethod
    def _circle_rect(cx: float, cy: float, r: float, rect) -> bool:
        rx, ry, rw, rh = rect
        nx = clamp(cx, rx, rx + rw)
        ny = clamp(cy, ry, ry + rh)
        return (cx - nx) ** 2 + (cy - ny) ** 2 < r * r

    @staticmethod
    def _circle_triangle(cx: float, cy: float, r: float, pts) -> bool:
        (ax, ay), (bx, by), (ex, ey) = pts

        def edge_side(px, py, x1, y1, x2, y2):
            return (px - x2) * (y1 - y2) - (x1 - x2) * (py - y2)

        d1 = edge_side(cx, cy, ax, ay, bx, by)
        d2 = edge_side(cx, cy, bx, by, ex, ey)
        d3 = edge_side(cx, cy, ex, ey, ax, ay)
        has_neg = d1 < 0 or d2 < 0 or d3 < 0
        has_pos = d1 > 0 or d2 > 0 or d3 > 0
        if not (has_neg and has_pos):
            return True

        def dist2(px, py, x1, y1, x2, y2):
            vx, vy = x2 - x1, y2 - y1
            wx, wy = px - x1, py - y1
            length2 = vx * vx + vy * vy
            t = 0.0 if length2 == 0.0 else clamp((wx * vx + wy * vy) / length2, 0.0, 1.0)
            qx, qy = x1 + vx * t, y1 + vy * t
            return (px - qx) ** 2 + (py - qy) ** 2

        r2 = r * r
        return (
            dist2(cx, cy, ax, ay, bx, by) < r2
            or dist2(cx, cy, bx, by, ex, ey) < r2
            or dist2(cx, cy, ex, ey, ax, ay) < r2
        )

    def _collides_obstacles(self, x: float, y: float) -> bool:
        r = self.radius
        for obstacle in self.corridor.obstacles:
            if obstacle["x1"] < x - r:
                continue
            if obstacle["x0"] > x + r:
                break
            for rect in obstacle["rects"]:
                if self._circle_rect(x, y, r, rect):
                    return True
            for sx, sy, sw, sh, orient in obstacle["spikes"]:
                if orient == "up":
                    pts = ((sx, sy + sh), (sx + sw * 0.5, sy), (sx + sw, sy + sh))
                else:
                    pts = ((sx, sy), (sx + sw * 0.5, sy + sh), (sx + sw, sy))
                if self._circle_triangle(x, y, r, pts):
                    return True
        return False

    def _spawn_trail_spark(self) -> None:
        if len(self.particles) > 220:
            return
        color = self.accent
        back = 10.0 if not self.mini else 7.0
        self.particles.append(
            Particle(
                self.player_x - back,
                self.player_y + random.uniform(-2.0, 2.0),
                -self.speed * random.uniform(0.10, 0.30),
                random.uniform(-26.0, 26.0),
                random.uniform(0.25, 0.55),
                random.uniform(1.5, 3.4) * (0.7 if self.mini else 1.0),
                blend(color, (255, 255, 255), random.uniform(0.0, 0.5)),
            )
        )

    def _die(self) -> None:
        self.state = "dead"
        self.dead_timer = 0.0
        self.shake = 20.0
        self.distance = max(0, int(self.player_x / 10.0))
        if self.distance > self.best:
            self.best = self.distance
            save_best(self.best)
            self.new_best = True
        else:
            self.new_best = False
        colors = (self.accent, RED, (255, 255, 255), GOLD)
        for _ in range(70):
            angle = random.uniform(0.0, math.tau)
            speed = random.uniform(60.0, 520.0)
            self.particles.append(
                Particle(
                    self.player_x,
                    self.player_y,
                    math.cos(angle) * speed,
                    math.sin(angle) * speed,
                    random.uniform(0.35, 1.1),
                    random.uniform(2.0, 5.0),
                    random.choice(colors),
                    gravity=420.0,
                )
            )
        self.trail.clear()

    def _update_particles(self, dt: float) -> None:
        if not self.particles:
            return
        for p in self.particles:
            p.life -= dt
            p.vy += p.gravity * dt
            p.vx *= (1.0 - 1.8 * dt)
            p.vy *= (1.0 - 1.2 * dt)
            p.x += p.vx * dt
            p.y += p.vy * dt
        self.particles = [p for p in self.particles if p.life > 0.0]

    # -- toasts ------------------------------------------------------------ #

    def toast(self, text: str, color, life: float = 1.6) -> None:
        self.toasts.append({"text": text, "color": color, "life": life, "max": life})

    # -- drawing ----------------------------------------------------------- #

    def keys_held(self) -> bool:
        keys = pygame.key.get_pressed()
        return bool(
            keys[pygame.K_w] or keys[pygame.K_SPACE] or keys[pygame.K_UP]
        ) or bool(pygame.mouse.get_pressed()[0])

    def draw(self) -> None:
        self.screen.blit(self.bg, (0, 0))
        self._draw_stars()

        if self.state == "menu":
            self._draw_menu()
        else:
            self._draw_world()
            self._draw_hud()
            if self.state == "paused":
                self._draw_pause()
            elif self.state == "dead":
                self._draw_death()

    def _draw_stars(self) -> None:
        for star in self.stars:
            x = (star["x"] - self.camera_x * star["p"]) % (WIDTH + 40) - 20
            twinkle = 0.55 + 0.45 * math.sin(self.t * 2.2 + star["phase"])
            c = int(70 + 95 * twinkle)
            color = (c, int(c * 1.05), min(255, int(c * 1.35)))
            pygame.draw.circle(self.screen, color, (int(x), int(star["y"])), star["r"])

        # Faint parallax grid.
        offset = int((self.camera_x * 0.35) % 80)
        grid = (20, 28, 52)
        for gx in range(-offset, WIDTH, 80):
            pygame.draw.line(self.screen, grid, (gx, 0), (gx, HEIGHT))
        for gy in range(0, HEIGHT, 80):
            pygame.draw.line(self.screen, (16, 22, 42), (0, gy), (WIDTH, gy))

    def _draw_world(self) -> None:
        view_x = self.camera_x + self.shake_x
        view_y = self.shake_y
        accent = self.accent
        accent_dim = blend(WALL_FILL, accent, 0.38)
        accent_mid = blend(WALL_FILL, accent, 0.68)

        first = int((self.camera_x - 40.0) // BAR)
        last = int((self.camera_x + WIDTH + 40.0) // BAR)
        for i in range(first, last + 1):
            ceil_y, floor_y = self.corridor.bar(i)
            sx = int(i * BAR - view_x)
            top_edge = int(ceil_y + view_y)
            bottom_edge = int(floor_y + view_y)

            # Walls (overshoot the screen edges a little to hide the shake).
            pygame.draw.rect(self.screen, WALL_FILL, (sx, -16, int(BAR) + 1, top_edge + 16))
            pygame.draw.rect(
                self.screen, WALL_FILL, (sx, bottom_edge, int(BAR) + 1, HEIGHT - bottom_edge + 16)
            )

            # Block seams every 40 world px.
            if i % 5 == 0:
                pygame.draw.line(self.screen, WALL_LINE, (sx, 0), (sx, max(0, top_edge)))
                pygame.draw.line(
                    self.screen, WALL_LINE, (sx, min(HEIGHT, bottom_edge)), (sx, HEIGHT)
                )

            # Glowing inner rim.
            pygame.draw.rect(self.screen, accent_dim, (sx, top_edge - 7, int(BAR) + 1, 7))
            pygame.draw.rect(self.screen, accent_dim, (sx, bottom_edge, int(BAR) + 1, 7))
            pygame.draw.rect(
                self.screen, accent_mid, (sx, top_edge - 2, int(BAR) + 1, 2)
            )
            pygame.draw.rect(self.screen, accent_mid, (sx, bottom_edge, int(BAR) + 1, 2))

        self._draw_portals(view_x, view_y)
        self._draw_obstacles(view_x, view_y)
        self._draw_trail(view_x, view_y)
        self._draw_particles(view_x, view_y)
        if self.state != "dead":
            self._draw_player(view_x, view_y)
        self._draw_toasts()

    def _draw_portals(self, view_x: float, view_y: float) -> None:
        for portal in self.corridor.portals:
            sx = portal["x"] - view_x
            if sx < -140 or sx > WIDTH + 140:
                continue
            ceil_y, floor_y = self.corridor.bounds_at(portal["x"])
            top = int(ceil_y + view_y) - 16
            bottom = int(floor_y + view_y) + 16
            height = max(2, bottom - top)

            if portal["kind"] == "speed":
                color = ACCENTS[portal["tier"]]
                label = f"{SPEED_TIERS[portal['tier']]:.2f}x"
            elif portal["kind"] == "mini":
                color = MINI_COLOR
                label = "MINI"
            else:
                color = ACCENTS[0]
                label = "NORMAL"

            band = pygame.Surface((26, height), pygame.SRCALPHA)
            for row in range(height):
                fade = 1.0 - abs(row / max(1, height - 1) - 0.5) * 1.2
                band.fill((*color, int(70 * fade)), (0, row, 26, 1))
            self.screen.blit(band, (int(sx - 13), top))

            pygame.draw.line(self.screen, color, (sx - 13, top), (sx - 13, bottom), 2)
            pygame.draw.line(self.screen, color, (sx + 13, top), (sx + 13, bottom), 2)
            pygame.draw.rect(
                self.screen, color, (sx - 16, top - 6, 32, 6), border_radius=2
            )
            pygame.draw.rect(
                self.screen, color, (sx - 16, bottom, 32, 6), border_radius=2
            )

            text = self.font(17, True).render(label, True, color)
            self.screen.blit(text, text.get_rect(center=(int(sx), top - 20)))

    def _draw_obstacles(self, view_x: float, view_y: float) -> None:
        accent = self.accent
        block_fill = (17, 25, 46)
        block_grid = blend(block_fill, accent, 0.16)
        block_edge = blend(block_fill, accent, 0.72)
        spike_fill = (32, 16, 34)
        spike_edge = (255, 106, 124)
        spike_inner = (255, 58, 86)

        for obstacle in self.corridor.obstacles:
            if obstacle["x1"] < self.camera_x - 90.0:
                continue
            if obstacle["x0"] > self.camera_x + WIDTH + 90.0:
                break

            for index, rect in enumerate(obstacle["rects"]):
                rx, ry, rw, rh = rect
                screen_rect = pygame.Rect(
                    int(rx - view_x), int(ry + view_y), max(2, int(rw)), max(2, int(rh))
                )
                pygame.draw.rect(self.screen, block_fill, screen_rect)

                # Tile seams inside the block.
                gx = math.floor(rx / 36.0) * 36.0
                while gx < rx + rw:
                    if gx >= rx:
                        lx = int(gx - view_x)
                        pygame.draw.line(
                            self.screen, block_grid, (lx, screen_rect.top), (lx, screen_rect.bottom)
                        )
                    gx += 36.0
                gy = math.floor(ry / 36.0) * 36.0
                while gy < ry + rh:
                    if gy >= ry:
                        ly = int(gy + view_y)
                        pygame.draw.line(
                            self.screen, block_grid, (screen_rect.left, ly), (screen_rect.right, ly)
                        )
                    gy += 36.0

                pygame.draw.rect(self.screen, block_edge, screen_rect, 2)

                floor_side = obstacle["kind"] in ("block", "stairs") or (
                    obstacle["kind"] == "gate" and index == 0
                )
                if floor_side:
                    pygame.draw.line(
                        self.screen,
                        accent,
                        (screen_rect.left, screen_rect.top),
                        (screen_rect.right, screen_rect.top),
                        3,
                    )
                else:
                    pygame.draw.line(
                        self.screen,
                        accent,
                        (screen_rect.left, screen_rect.bottom - 1),
                        (screen_rect.right, screen_rect.bottom - 1),
                        3,
                    )

            for sx, sy, sw, sh, orient in obstacle["spikes"]:
                left = sx - view_x
                top = sy + view_y
                if orient == "up":
                    pts = [(left, top + sh), (left + sw * 0.5, top), (left + sw, top + sh)]
                else:
                    pts = [(left, top), (left + sw * 0.5, top + sh), (left + sw, top)]
                pygame.draw.polygon(self.screen, spike_fill, pts)
                pygame.draw.polygon(self.screen, spike_edge, pts, 2)
                cx = sum(p[0] for p in pts) / 3.0
                cy = sum(p[1] for p in pts) / 3.0
                inner = [(cx + (px - cx) * 0.52, cy + (py - cy) * 0.52) for px, py in pts]
                pygame.draw.polygon(self.screen, spike_inner, inner)

    def _draw_trail(self, view_x: float, view_y: float) -> None:
        points = self.trail
        n = len(points)
        if n < 2:
            return
        accent = self.accent
        for i in range(1, n):
            t = i / n
            x1 = points[i - 1][0] - view_x
            y1 = points[i - 1][1] + view_y
            x2 = points[i][0] - view_x
            y2 = points[i][1] + view_y
            color = blend(blend(WALL_FILL, accent, 0.25), blend(accent, (255, 255, 255), 0.55), t)
            width = max(1, int((2.0 + 9.0 * t) * (0.82 if self.mini else 1.0)))
            pygame.draw.line(self.screen, color, (x1, y1), (x2, y2), width)

    def _draw_particles(self, view_x: float, view_y: float) -> None:
        for p in self.particles:
            fade = clamp(p.life / p.max_life, 0.0, 1.0)
            color = blend(BG_BOTTOM, p.color, fade)
            radius = max(1, int(p.size * (0.5 + 0.5 * fade)))
            pygame.draw.circle(
                self.screen, color, (int(p.x - view_x), int(p.y + view_y)), radius
            )

    def _draw_player(self, view_x: float, view_y: float) -> None:
        sx = self.player_x - view_x
        sy = self.player_y + view_y
        r = 10.0 if not self.mini else 6.5
        accent = self.accent

        angle = math.atan2(self.slope, 1.0)
        base = [
            (r * 1.7, 0.0),
            (-r * 0.85, -r),
            (-r * 0.35, 0.0),
            (-r * 0.85, r),
        ]
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        pts = [(sx + px * cos_a - py * sin_a, sy + px * sin_a + py * cos_a) for px, py in base]
        pygame.draw.polygon(self.screen, (12, 16, 30), pts)
        pygame.draw.polygon(self.screen, accent, pts, 3)
        pygame.draw.polygon(
            self.screen, (250, 253, 255), [(sx + (x - sx) * 0.55, sy + (y - sy) * 0.55) for x, y in pts]
        )

    # -- HUD --------------------------------------------------------------- #

    def _draw_hud(self) -> None:
        dist = self.distance
        big = self.font(46, True).render(f"{dist}", True, TEXT)
        unit = self.font(22, True).render(" m", True, MUTED)
        self.screen.blit(big, (34, 22))
        self.screen.blit(unit, (34 + big.get_width(), 46))

        best_text = f"BEST  {max(self.best, dist):,} m"
        self.screen.blit(self.font(17, True).render(best_text, True, MUTED), (36, 74))

        accent = self.accent
        speed_text = f"SPEED {SPEED_TIERS[self.tier]:.2f}x"
        label = self.font(22, True).render(speed_text, True, accent)
        self.screen.blit(label, (WIDTH - label.get_width() - 34, 24))

        mode = "MINI WAVE" if self.mini else "WAVE"
        mode_color = MINI_COLOR if self.mini else TEXT
        mode_surf = self.font(15, True).render(mode, True, mode_color)
        self.screen.blit(mode_surf, (WIDTH - mode_surf.get_width() - 34, 54))

        for i in range(MAX_TIER + 1):
            pip_w = 26
            x = WIDTH - 34 - (MAX_TIER - i + 1) * (pip_w + 5) + 5
            color = ACCENTS[min(i, MAX_TIER)] if i <= self.tier else (38, 48, 70)
            pygame.draw.rect(self.screen, color, (x, 82, pip_w, 5), border_radius=2)

        if self.run_time < 8.0 and self.state == "playing":
            hint = self.font(16, True).render(
                "HOLD   W  /  SPACE  /  \u2191   TO RISE", True, MUTED
            )
            self.screen.blit(hint, hint.get_rect(center=(WIDTH // 2, HEIGHT - 34)))

    def _draw_toasts(self) -> None:
        y = 138
        for toast in self.toasts:
            life = toast["life"] / toast["max"]
            appear = clamp((1.0 - life) * 8.0, 0.0, 1.0)
            fade = clamp(life * 2.0, 0.0, 1.0)
            color = blend(BG_BOTTOM, toast["color"], fade)
            text = self.font(26, True).render(toast["text"], True, color)
            text.set_alpha(int(255 * min(appear, fade)))
            self.screen.blit(text, text.get_rect(center=(WIDTH // 2, int(y))))
            y += 34

    # -- menus / overlays -------------------------------------------------- #

    def _draw_keycap(self, label: str, center, width: int, size: int = 20) -> None:
        rect = pygame.Rect(0, 0, width, 42)
        rect.center = center
        pygame.draw.rect(self.screen, KEY_CAP, rect, border_radius=9)
        pygame.draw.rect(self.screen, KEY_CAP_EDGE, rect, 2, border_radius=9)
        text = self.font(size, True).render(label, True, TEXT)
        self.screen.blit(text, text.get_rect(center=rect.center))

    def _draw_menu(self) -> None:
        pulse = 0.5 + 0.5 * math.sin(self.t * 2.4)

        # Decorative wave lines near the bottom.
        for layer, (amp, speed, color) in enumerate(
            ((22.0, 1.1, (0, 170, 205)), (14.0, -1.6, (105, 58, 185)))
        ):
            points = []
            base_y = HEIGHT - 116 + layer * 32
            for x in range(0, WIDTH + 8, 8):
                y = base_y + math.sin((x + self.t * 180.0 * speed) * 0.011) * amp
                points.append((x, y))
            pygame.draw.lines(self.screen, color, False, points, 2)

        # Title.
        title = self.font(104, True).render("WAVE", True, TEXT)
        self.screen.blit(title, title.get_rect(center=(WIDTH // 2, 178)))
        accent = ACCENTS[0]
        sub = self.font(38, True).render("C H A L L E N G E", True, accent)
        self.screen.blit(sub, sub.get_rect(center=(WIDTH // 2, 245)))

        tag = self.font(18).render(
            "an endless Geometry Dash-style wave run", True, MUTED
        )
        self.screen.blit(tag, tag.get_rect(center=(WIDTH // 2, 286)))

        # Controls.
        pygame.draw.rect(
            self.screen, (14, 21, 38), pygame.Rect(WIDTH // 2 - 330, 336, 660, 112), border_radius=16
        )
        pygame.draw.rect(
            self.screen,
            (36, 50, 82),
            pygame.Rect(WIDTH // 2 - 330, 336, 660, 112),
            2,
            border_radius=16,
        )
        self._draw_keycap("W", (WIDTH // 2 - 120, 378), 54)
        self._draw_keycap("SPACE", (WIDTH // 2, 378), 104)
        self._draw_keycap("\u2191", (WIDTH // 2 + 120, 378), 54)
        hold = self.font(20, True).render("HOLD ANY OF THESE TO FLY UP", True, TEXT)
        self.screen.blit(hold, hold.get_rect(center=(WIDTH // 2, 424)))
        tip = self.font(14).render(
            "dodge spikes, blocks & gates  \u2022  mini wave is smaller, steeper & floaty",
            True,
            MUTED,
        )
        self.screen.blit(tip, tip.get_rect(center=(WIDTH // 2, 492)))

        if self.best:
            best = self.font(20, True).render(f"BEST  {self.best:,} m", True, GOLD)
            self.screen.blit(best, best.get_rect(center=(WIDTH // 2, 532)))

        color = blend(MUTED, accent, pulse)
        prompt = self.font(28, True).render("PRESS  SPACE  TO START", True, color)
        self.screen.blit(prompt, prompt.get_rect(center=(WIDTH // 2, 592)))

        foot = self.font(14).render("P / ESC pause    \u2022    R restart", True, (90, 104, 132))
        self.screen.blit(foot, foot.get_rect(center=(WIDTH // 2, HEIGHT - 46)))

    def _overlay(self, alpha: int = 170) -> None:
        veil = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        veil.fill((5, 8, 18, alpha))
        self.screen.blit(veil, (0, 0))

    def _draw_pause(self) -> None:
        self._overlay(165)
        title = self.font(64, True).render("PAUSED", True, TEXT)
        self.screen.blit(title, title.get_rect(center=(WIDTH // 2, 300)))
        hint = self.font(20, True).render("P / ESC to resume    \u2022    R to restart", True, MUTED)
        self.screen.blit(hint, hint.get_rect(center=(WIDTH // 2, 372)))

    def _draw_death(self) -> None:
        self._overlay(160)
        title_color = RED
        title = self.font(72, True).render("CRASHED", True, title_color)
        self.screen.blit(title, title.get_rect(center=(WIDTH // 2, 246)))

        dist = self.font(42, True).render(f"{self.distance:,} m", True, TEXT)
        self.screen.blit(dist, dist.get_rect(center=(WIDTH // 2, 326)))

        if getattr(self, "new_best", False):
            best = self.font(24, True).render("NEW BEST!", True, GOLD)
        else:
            best = self.font(24, True).render(f"BEST  {self.best:,} m", True, MUTED)
        self.screen.blit(best, best.get_rect(center=(WIDTH // 2, 372)))

        if self.dead_timer > 0.35:
            pulse = 0.55 + 0.45 * math.sin(self.t * 4.0)
            color = blend(MUTED, TEXT, pulse)
            prompt = self.font(26, True).render(
                "PRESS  SPACE  /  R  TO RETRY", True, color
            )
            self.screen.blit(prompt, prompt.get_rect(center=(WIDTH // 2, 472)))

    # -- main loop --------------------------------------------------------- #

    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            for event in pygame.event.get():
                self.handle_event(event)
            if not self.running:
                break
            self.update(dt, self.keys_held())
            self.draw()
            pygame.display.flip()

        if self.distance > self.best:
            self.best = self.distance
            save_best(self.best)
        pygame.quit()


def main() -> None:
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    game = Game()
    game.run()


if __name__ == "__main__":
    main()
