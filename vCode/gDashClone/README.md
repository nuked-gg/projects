# Wave Challenge

An endless, Geometry Dash-style **wave** game built with pygame. Thread a
neon obstacle course that never ends, gets tighter and twistier the farther you
go, and throws speed and mini-wave portals at you along the way.

## Run it

```bash
cd ~/codingStuff/projects/vCode
python3 -m pip install pygame      # only dependency
python3 game.py
```

Or run it from VS Code with the Python extension (open this folder, open
`game.py`, press **F5** / Run).

## Controls

| Input | Action |
| --- | --- |
| **W**, **Space**, **↑** (hold) | Fly diagonally up |
| Release | Fly diagonally down |
| Left mouse (hold) | Alternative rise input |
| **P** / **Esc** | Pause / resume |
| **R** | Restart run |
| **Esc** on the crash screen | Back to menu |

Hold to rise, let go to dive. Your wave travels diagonally in whichever
vertical direction is active, so plan a couple of turns ahead.

## Features

- **Endless procedural level** – cosine-interpolated cave that is always
  physically threadable, generated far ahead of the player.
- **Actual obstacles, not just a tunnel** – floor and ceiling spike rows,
  solid blocks, stepped block towers, hanging blocks, and gates built from
  blocks and spikes. Every structure is generated with a guaranteed safe
  opening sized for the wave's hitbox.
- **Difficulty ramp** – the tunnel narrows from ~300 px to ~205 px, turns get
  denser, and obstacles arrive more often and hit harder as distance grows.
  Every run uses a fresh random seed.
- **Multiple speeds** – five speed tiers (1.00x, 1.28x, 1.60x, 1.95x, 2.35x)
  delivered by glowing speed portals.
- **Mini wave with real physics** – mini portals switch to a smaller hitbox, a
  steeper angle, and momentum-based steering, so direction changes carve
  curves instead of snapping. Normal portals restore the regular instant-snap
  wave.
- **Game feel** – bigger neon trail, sparks, screen shake, portal gates, speed
  pips, toasts, animated starfield, pause, crash screen, live distance, and a
  persistent best score.
- **High score** saved to `highscore.txt` next to `game.py`.

## Files

- `game.py` – the whole game.
- `highscore.txt` – created automatically after your first crash.

Tested with Python 3.14 and pygame 2.6.1. Any Python 3.9+ / pygame 2.x should
work.
