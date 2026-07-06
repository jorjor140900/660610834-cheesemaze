import argparse
import random
import time
from collections import deque
from dataclasses import dataclass

try:
    import tkinter as tk
except ImportError:  # Allows --headless on systems without Tk installed.
    tk = None


GRID_SIZE = 30
UNIT_CM = 16
MOUSE_DIAMETER_CM = 12
CUTOFF_SECONDS = 180
SIMULATION_SPEED = 6.0
STEP_SECONDS = 1
STEP_DELAY_MS = int(1000 / SIMULATION_SPEED)
START_DELAY_MS = 3000

CELL_PX = 20
MARGIN_PX = 64

DIRECTIONS = {
    "N": (0, -1, "S"),
    "E": (1, 0, "W"),
    "S": (0, 1, "N"),
    "W": (-1, 0, "E"),
}


@dataclass(frozen=True)
class RunResult:
    won: bool
    game_seconds: int
    steps: int
    real_seconds: float
    path_length: int


class Maze:
    def __init__(self, size=GRID_SIZE, seed=None):
        self.size = size
        self.seed = seed
        self.random = random.Random(seed)
        self.walls = [
            [set(DIRECTIONS.keys()) for _ in range(size)]
            for _ in range(size)
        ]
        self.entrance = (0, 0)
        self.exit = (size - 1, size - 1)
        self._generate()
        self.walls[0][0].discard("W")
        self.walls[size - 1][size - 1].discard("E")

    def _generate(self):
        stack = [(0, 0)]
        visited = {(0, 0)}

        while stack:
            x, y = stack[-1]
            neighbors = []

            for direction, (dx, dy, opposite) in DIRECTIONS.items():
                nx, ny = x + dx, y + dy
                if 0 <= nx < self.size and 0 <= ny < self.size and (nx, ny) not in visited:
                    neighbors.append((direction, nx, ny, opposite))

            if not neighbors:
                stack.pop()
                continue

            direction, nx, ny, opposite = self.random.choice(neighbors)
            self.walls[y][x].remove(direction)
            self.walls[ny][nx].remove(opposite)
            visited.add((nx, ny))
            stack.append((nx, ny))

    def neighbors(self, cell):
        x, y = cell
        for direction, (dx, dy, _) in DIRECTIONS.items():
            if direction not in self.walls[y][x]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < self.size and 0 <= ny < self.size:
                    yield (nx, ny)

    def shortest_path(self, start, goal):
        queue = deque([start])
        previous = {start: None}

        while queue:
            current = queue.popleft()
            if current == goal:
                break

            for nxt in self.neighbors(current):
                if nxt not in previous:
                    previous[nxt] = current
                    queue.append(nxt)

        if goal not in previous:
            return []

        path = []
        current = goal
        while current is not None:
            path.append(current)
            current = previous[current]
        path.reverse()
        return path


def make_winnable_maze(seed=None, max_path_steps=CUTOFF_SECONDS):
    base_random = random.Random(seed)
    attempts = 0

    while True:
        attempts += 1
        maze_seed = base_random.randrange(1_000_000_000) if seed is not None else None
        maze = Maze(seed=maze_seed)
        path = maze.shortest_path(maze.entrance, maze.exit)
        path_steps = max(0, len(path) - 1)

        if path_steps <= max_path_steps:
            return maze, path

        if seed is None:
            continue

        # Keep deterministic seeded runs bounded; fall back to the shortest
        # exact route even if it creates a failure demonstration.
        if attempts >= 200:
            return maze, path


class MouseRunner:
    def __init__(self, maze):
        self.maze = maze
        self.position = maze.entrance
        self.visited = {self.position}
        self.steps = 0
        self.game_seconds = 0
        self.finished = False
        self.won = False
        self.current_smell_path = maze.shortest_path(self.position, maze.exit)
        self.facing = self._path_direction(self.current_smell_path)

    def _path_direction(self, path):
        if len(path) < 2:
            return (1, 0)
        x1, y1 = path[0]
        x2, y2 = path[1]
        return (x2 - x1, y2 - y1)

    def step(self):
        if self.finished:
            return

        self.current_smell_path = self.maze.shortest_path(self.position, self.maze.exit)
        if not self.current_smell_path:
            self.finished = True
            self.won = False
            return

        if self.position == self.maze.exit:
            self.finished = True
            self.won = True
            return

        next_cell = self.current_smell_path[1]
        x, y = self.position
        nx, ny = next_cell
        self.facing = (nx - x, ny - y)
        self.position = next_cell
        self.visited.add(next_cell)
        self.steps += 1
        self.game_seconds += STEP_SECONDS

        if self.position == self.maze.exit:
            self.finished = True
            self.won = True
        elif self.game_seconds >= CUTOFF_SECONDS:
            self.finished = True
            self.won = False

    def run_to_end(self):
        started_at = time.perf_counter()
        while not self.finished:
            self.step()
        real_seconds = time.perf_counter() - started_at
        full_path = self.maze.shortest_path(self.maze.entrance, self.maze.exit)
        return RunResult(
            won=self.won,
            game_seconds=self.game_seconds,
            steps=self.steps,
            real_seconds=real_seconds,
            path_length=max(0, len(full_path) - 1),
        )


class MazeApp:
    def __init__(self, root, maze):
        self.root = root
        self.maze = maze
        self.runner = MouseRunner(maze)
        self.wait_started_at = time.perf_counter()
        self.started_at = None
        self.running = False
        self.delay_ms = STEP_DELAY_MS

        width = GRID_SIZE * CELL_PX + MARGIN_PX * 2
        height = GRID_SIZE * CELL_PX + MARGIN_PX * 2 + 72
        self.canvas_width = width
        self.canvas_height = height

        root.title("Mouse Maze - Cheese Smell Shortest Path")
        root.resizable(False, False)

        self.canvas = tk.Canvas(root, width=width, height=height, bg="#4a301f", highlightthickness=0)
        self.canvas.pack()
        self.status_id = None
        self.draw()
        self.root.after(250, self.countdown)

    def cell_rect(self, x, y, inset=0):
        left = MARGIN_PX + x * CELL_PX + inset
        top = MARGIN_PX + y * CELL_PX + inset
        right = MARGIN_PX + (x + 1) * CELL_PX - inset
        bottom = MARGIN_PX + (y + 1) * CELL_PX - inset
        return left, top, right, bottom

    def draw(self):
        self.canvas.delete("all")
        self.draw_underground()
        self.draw_cells()
        self.draw_walls()
        self.draw_labels()

    def draw_underground(self):
        maze_left = MARGIN_PX
        maze_top = MARGIN_PX
        maze_right = MARGIN_PX + GRID_SIZE * CELL_PX
        maze_bottom = MARGIN_PX + GRID_SIZE * CELL_PX

        self.canvas.create_rectangle(0, 0, self.canvas_width, self.canvas_height, fill="#4a301f", outline="")
        self.canvas.create_rectangle(0, maze_bottom + 14, self.canvas_width, self.canvas_height, fill="#ead9bd", outline="")
        self.canvas.create_rectangle(maze_left, maze_top, maze_right, maze_bottom, fill="#7a5134", outline="")
        self.canvas.create_rectangle(maze_left - 22, maze_top + 4, maze_left + 2, maze_top + CELL_PX - 4, fill="#7a5134", outline="")

        border = "#2b1b12"
        self.canvas.create_line(maze_left, maze_top, maze_right, maze_top, fill=border, width=3)
        self.canvas.create_line(maze_left, maze_top + CELL_PX, maze_left, maze_bottom, fill=border, width=3)
        self.canvas.create_line(maze_left, maze_bottom, maze_right, maze_bottom, fill=border, width=3)
        self.canvas.create_line(maze_right, maze_top, maze_right, maze_bottom - CELL_PX, fill=border, width=3)

        for y in range(GRID_SIZE):
            for x in range(GRID_SIZE):
                left, top, _, _ = self.cell_rect(x, y)
                dot_x = left + 4 + ((x * 7 + y * 11) % max(1, CELL_PX - 8))
                dot_y = top + 4 + ((x * 13 + y * 5) % max(1, CELL_PX - 8))
                color = "#6a452d" if (x + y) % 2 == 0 else "#8b6241"
                self.canvas.create_oval(dot_x, dot_y, dot_x + 2, dot_y + 2, fill=color, outline="")

    def draw_cells(self):
        for x, y in self.runner.visited:
            self.canvas.create_rectangle(
                *self.cell_rect(x, y, 2),
                fill="#9a734e",
                outline="",
            )

        for x, y in self.runner.current_smell_path[:12]:
            self.canvas.create_rectangle(
                *self.cell_rect(x, y, 5),
                fill="#c99a45",
                outline="",
            )

        self.draw_cheese()
        self.draw_mouse()

    def draw_cheese(self):
        _, ey = self.maze.exit
        maze_right = MARGIN_PX + GRID_SIZE * CELL_PX
        exit_y = MARGIN_PX + ey * CELL_PX + CELL_PX / 2
        left = maze_right + 8
        right = maze_right + 58
        top = exit_y - 22
        bottom = exit_y + 20

        self.canvas.create_rectangle(maze_right - 1, exit_y - 6, left + 7, exit_y + 6, fill="#9a734e", outline="")
        self.canvas.create_oval(left + 2, bottom - 3, right + 3, bottom + 6, fill="#3b2417", outline="")
        points = [
            left,
            bottom - 5,
            left + 36,
            top + 2,
            right,
            top + 12,
            right - 5,
            bottom,
        ]
        front = [
            left,
            bottom - 5,
            left + 36,
            top + 2,
            left + 31,
            bottom - 2,
        ]
        side = [
            left + 36,
            top + 2,
            right,
            top + 12,
            right - 5,
            bottom,
            left + 31,
            bottom - 2,
        ]
        self.canvas.create_polygon(points, fill="#f1b928", outline="")
        self.canvas.create_polygon(front, fill="#ffd84d", outline="#7c5200", width=2)
        self.canvas.create_polygon(side, fill="#e5a923", outline="#7c5200", width=2)
        self.canvas.create_line(left + 5, bottom - 8, right - 8, bottom - 3, fill="#c68112", width=2)
        self.canvas.create_oval(left + 15, bottom - 22, left + 24, bottom - 13, fill="#fff2a0", outline="#bf7d0e", width=2)
        self.canvas.create_oval(left + 27, bottom - 13, left + 35, bottom - 5, fill="#fff2a0", outline="#bf7d0e", width=2)
        self.canvas.create_oval(left + 8, bottom - 12, left + 14, bottom - 6, fill="#fff2a0", outline="#bf7d0e", width=1)
        self.canvas.create_oval(left + 41, top + 14, left + 48, top + 21, fill="#f7cd49", outline="#b56f0c", width=1)

    def draw_mouse(self):
        mx, my = self.runner.position
        cx = MARGIN_PX + mx * CELL_PX + CELL_PX / 2
        cy = MARGIN_PX + my * CELL_PX + CELL_PX / 2
        dx, dy = self.runner.facing

        body = "#8a8d93"
        outline = "#303238"
        ear = "#c9a1a6"
        nose = "#2b2020"
        eye = "#111111"
        tail = "#a46a78"

        if dx >= 1:
            self.canvas.create_line(cx - 6, cy + 2, cx - 9, cy + 5, cx - 7, cy + 7, fill=tail, width=2, smooth=True)
            self.canvas.create_oval(cx - 7, cy - 5, cx + 4, cy + 5, fill=body, outline=outline, width=1)
            self.canvas.create_oval(cx + 1, cy - 4, cx + 8, cy + 4, fill=body, outline=outline, width=1)
            self.canvas.create_oval(cx + 2, cy - 7, cx + 6, cy - 3, fill=ear, outline=outline, width=1)
            self.canvas.create_oval(cx + 5, cy - 1, cx + 7, cy + 1, fill=eye, outline="")
            self.canvas.create_oval(cx + 7, cy + 1, cx + 9, cy + 3, fill=nose, outline="")
        elif dx <= -1:
            self.canvas.create_line(cx + 6, cy + 2, cx + 9, cy + 5, cx + 7, cy + 7, fill=tail, width=2, smooth=True)
            self.canvas.create_oval(cx - 4, cy - 5, cx + 7, cy + 5, fill=body, outline=outline, width=1)
            self.canvas.create_oval(cx - 8, cy - 4, cx - 1, cy + 4, fill=body, outline=outline, width=1)
            self.canvas.create_oval(cx - 6, cy - 7, cx - 2, cy - 3, fill=ear, outline=outline, width=1)
            self.canvas.create_oval(cx - 7, cy - 1, cx - 5, cy + 1, fill=eye, outline="")
            self.canvas.create_oval(cx - 9, cy + 1, cx - 7, cy + 3, fill=nose, outline="")
        elif dy <= -1:
            self.canvas.create_line(cx - 2, cy + 6, cx - 5, cy + 9, cx - 7, cy + 7, fill=tail, width=2, smooth=True)
            self.canvas.create_oval(cx - 5, cy - 4, cx + 5, cy + 7, fill=body, outline=outline, width=1)
            self.canvas.create_oval(cx - 4, cy - 8, cx + 4, cy - 1, fill=body, outline=outline, width=1)
            self.canvas.create_oval(cx - 7, cy - 6, cx - 3, cy - 2, fill=ear, outline=outline, width=1)
            self.canvas.create_oval(cx + 3, cy - 6, cx + 7, cy - 2, fill=ear, outline=outline, width=1)
            self.canvas.create_oval(cx - 2, cy - 7, cx, cy - 5, fill=eye, outline="")
            self.canvas.create_oval(cx + 1, cy - 7, cx + 3, cy - 5, fill=eye, outline="")
            self.canvas.create_oval(cx - 1, cy - 9, cx + 1, cy - 7, fill=nose, outline="")
        else:
            self.canvas.create_line(cx - 2, cy - 6, cx - 5, cy - 9, cx - 7, cy - 7, fill=tail, width=2, smooth=True)
            self.canvas.create_oval(cx - 5, cy - 7, cx + 5, cy + 4, fill=body, outline=outline, width=1)
            self.canvas.create_oval(cx - 4, cy + 1, cx + 4, cy + 8, fill=body, outline=outline, width=1)
            self.canvas.create_oval(cx - 7, cy + 2, cx - 3, cy + 6, fill=ear, outline=outline, width=1)
            self.canvas.create_oval(cx + 3, cy + 2, cx + 7, cy + 6, fill=ear, outline=outline, width=1)
            self.canvas.create_oval(cx - 2, cy + 5, cx, cy + 7, fill=eye, outline="")
            self.canvas.create_oval(cx + 1, cy + 5, cx + 3, cy + 7, fill=eye, outline="")
            self.canvas.create_oval(cx - 1, cy + 7, cx + 1, cy + 9, fill=nose, outline="")

    def draw_walls(self):
        for y in range(self.maze.size):
            for x in range(self.maze.size):
                left, top, right, bottom = self.cell_rect(x, y)
                walls = self.maze.walls[y][x]
                if "N" in walls:
                    self.canvas.create_line(left, top, right, top, fill="#2b1b12", width=3)
                if "E" in walls:
                    self.canvas.create_line(right, top, right, bottom, fill="#2b1b12", width=3)
                if "S" in walls:
                    self.canvas.create_line(left, bottom, right, bottom, fill="#2b1b12", width=3)
                if "W" in walls:
                    self.canvas.create_line(left, top, left, bottom, fill="#2b1b12", width=3)

        entrance_y = MARGIN_PX + CELL_PX // 2
        exit_y = MARGIN_PX + (GRID_SIZE - 1) * CELL_PX + CELL_PX // 2
        self.canvas.create_text(MARGIN_PX - 26, entrance_y, text="IN", anchor="e", fill="#dcecff", font=("Segoe UI", 10, "bold"))
        self.canvas.create_text(MARGIN_PX + GRID_SIZE * CELL_PX + 30, exit_y - 28, text="OUT", anchor="center", fill="#fff2a8", font=("Segoe UI", 10, "bold"))

    def draw_labels(self):
        y = MARGIN_PX + GRID_SIZE * CELL_PX + 24
        remaining = max(0, CUTOFF_SECONDS - self.runner.game_seconds)
        status = (
            f"30 x 30 maze | unit: {UNIT_CM} cm | mouse: {MOUSE_DIAMETER_CM} cm | "
            f"step: {self.runner.steps} | mouse time: {self.runner.game_seconds}s | sim cutoff: {remaining}s"
        )
        self.canvas.create_text(MARGIN_PX, y, anchor="w", text=status, fill="#242424", font=("Segoe UI", 10))
        if self.started_at is None:
            elapsed = time.perf_counter() - self.wait_started_at
            start_remaining = max(0, int((START_DELAY_MS / 1000 - elapsed) + 0.999))
            helper = f"Mouse starts in {start_remaining}s. Simulation runs {SIMULATION_SPEED:g}x faster than real time."
        else:
            helper = f"Cheese smell chooses the shortest path each step. Simulation runs {SIMULATION_SPEED:g}x faster than real time."
        self.canvas.create_text(
            MARGIN_PX,
            y + 24,
            anchor="w",
            text=helper,
            fill="#565656",
            font=("Segoe UI", 9),
        )

    def countdown(self):
        if self.started_at is not None:
            return

        elapsed_ms = (time.perf_counter() - self.wait_started_at) * 1000
        if elapsed_ms >= START_DELAY_MS:
            self.running = True
            self.started_at = time.perf_counter()
            self.draw()
            self.root.after(self.delay_ms, self.tick)
            return

        self.draw()
        self.root.after(250, self.countdown)

    def tick(self):
        if not self.running:
            return

        self.runner.step()
        self.draw()

        if self.runner.finished:
            self.running = False
            real_seconds = time.perf_counter() - self.started_at
            result = RunResult(
                won=self.runner.won,
                game_seconds=self.runner.game_seconds,
                steps=self.runner.steps,
                real_seconds=real_seconds,
                path_length=max(0, len(self.maze.shortest_path(self.maze.entrance, self.maze.exit)) - 1),
            )
            self.finish(result)
            return

        self.root.after(self.delay_ms, self.tick)

    def finish(self, result):
        message = (
            f"SUCCESS: cheese reached in {result.game_seconds} simulated seconds "
            f"({result.steps} steps)."
            if result.won
            else f"FAILED: mouse died after {result.game_seconds} simulated seconds."
        )
        print(message)
        print(f"Real display time: {result.real_seconds:.2f} seconds at {SIMULATION_SPEED:g}x speed.")

        cx = MARGIN_PX + GRID_SIZE * CELL_PX / 2
        cy = MARGIN_PX + GRID_SIZE * CELL_PX / 2
        overlay_width = 500
        overlay_height = 112
        title = "SUCCESS" if result.won else "FAILED"
        detail = (
            f"Cheese reached in {result.game_seconds} simulated seconds ({result.steps} steps)."
            if result.won
            else f"Mouse died after {result.game_seconds} simulated seconds."
        )

        self.canvas.create_rectangle(
            cx - overlay_width / 2,
            cy - overlay_height / 2,
            cx + overlay_width / 2,
            cy + overlay_height / 2,
            fill="#fffaf0",
            outline="#2f2a24",
            width=2,
        )
        self.canvas.create_text(cx, cy - 30, text=title, fill="#242424", font=("Segoe UI", 14, "bold"))
        self.canvas.create_text(
            cx,
            cy - 4,
            text=detail,
            width=overlay_width - 36,
            justify="center",
            fill="#242424",
            font=("Segoe UI", 12, "bold"),
        )
        self.canvas.create_text(
            cx,
            cy + 28,
            text=f"Path length: {result.path_length} units. Real display time: {result.real_seconds:.2f}s.",
            fill="#565656",
            font=("Segoe UI", 10),
        )


def run_headless(seed=None):
    maze, path = make_winnable_maze(seed=seed)
    runner = MouseRunner(maze)
    result = runner.run_to_end()
    status = "SUCCESS" if result.won else "FAILED"
    print(f"{status}: cheese reached in {result.game_seconds} simulated seconds ({result.steps} steps)." if result.won else f"{status}: mouse died after {result.game_seconds} simulated seconds.")
    print(f"Maze: {GRID_SIZE}x{GRID_SIZE}, unit: {UNIT_CM} cm, mouse diameter: {MOUSE_DIAMETER_CM} cm.")
    print(f"Shortest entrance-to-exit path: {result.path_length} units.")
    print(f"Computation-only time: {result.real_seconds:.6f} seconds.")
    print(f"GUI mode runs at {SIMULATION_SPEED:g}x speed, so the 3-minute simulated cutoff displays in at most {CUTOFF_SECONDS / SIMULATION_SPEED:.1f} real seconds.")
    return 0 if result.won else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="30x30 mouse maze game with cheese-smell shortest-path navigation.")
    parser.add_argument("--headless", action="store_true", help="Run the simulation without opening a GUI.")
    parser.add_argument("--seed", type=int, default=None, help="Optional random seed for repeatable maze generation.")
    args = parser.parse_args(argv)

    if args.headless:
        return run_headless(seed=args.seed)

    if tk is None:
        print("Tkinter is not available on this Python install. Try: python maze_mouse_game.py --headless")
        return 2

    maze, _ = make_winnable_maze(seed=args.seed)
    root = tk.Tk()
    MazeApp(root, maze)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
