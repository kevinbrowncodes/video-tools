#!/usr/bin/env python3
"""Video Tools — Last Frame Extractor + Video Stitcher."""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Core logic (ffmpeg / ffprobe — no pip dependencies)
# ---------------------------------------------------------------------------

def _require_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError(
            "ffmpeg and ffprobe are required but not found in PATH.\n"
            "Install with: brew install ffmpeg"
        )


def get_video_info(video_path: str) -> dict:
    """Return basic stream/format metadata via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,nb_frames",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1",
            str(video_path),
        ],
        capture_output=True, text=True,
    )
    info = {}
    for line in result.stdout.strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    return info


def extract_last_frame(video_path: str, output_path: str | None = None) -> str:
    _require_ffmpeg()

    vp = Path(video_path)
    if not vp.exists():
        raise FileNotFoundError(f"Video file not found: {vp}")

    if output_path is None:
        output_path = str(vp.with_name(vp.stem + "_last_frame.png"))

    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=nb_frames",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(vp),
        ],
        capture_output=True, text=True,
    )
    nb_frames_str = probe.stdout.strip()

    if nb_frames_str.isdigit() and int(nb_frames_str) > 0:
        select = f"select=eq(n\\,{int(nb_frames_str) - 1})"
        cmd = ["ffmpeg", "-i", str(vp), "-vf", select, "-vframes", "1", "-y", output_path]
    else:
        cmd = ["ffmpeg", "-sseof", "-1", "-i", str(vp), "-vframes", "1", "-update", "1", "-y", output_path]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr.strip()}")

    if not Path(output_path).exists():
        raise RuntimeError("ffmpeg ran but no output file was created.")

    return output_path


def stitch_videos(video_paths: list[str], output_path: str, re_encode: bool = False) -> str:
    """Concatenate video_paths in order and write to output_path.

    re_encode=False  → stream-copy (fast, lossless, requires matching codecs)
    re_encode=True   → re-encode to H.264/AAC (slower, handles mixed formats)
    """
    _require_ffmpeg()

    if len(video_paths) < 2:
        raise ValueError("Provide at least 2 videos to stitch.")

    for p in video_paths:
        if not Path(p).exists():
            raise FileNotFoundError(f"Video file not found: {p}")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        list_file = f.name
        for p in video_paths:
            # escape single quotes in paths
            safe = str(Path(p).resolve()).replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

    try:
        if re_encode:
            # Build filter_complex concat for mixed-format inputs
            n = len(video_paths)
            inputs = []
            for p in video_paths:
                inputs += ["-i", p]
            filter_complex = "".join(f"[{i}:v][{i}:a]" for i in range(n))
            filter_complex += f"concat=n={n}:v=1:a=1[v][a]"
            cmd = (
                ["ffmpeg", "-y"]
                + inputs
                + [
                    "-filter_complex", filter_complex,
                    "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                    "-c:a", "aac", "-b:a", "192k",
                    output_path,
                ]
            )
        else:
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", list_file,
                "-c", "copy",
                output_path,
            ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed:\n{result.stderr.strip()}")

        if not Path(output_path).exists():
            raise RuntimeError("ffmpeg ran but no output file was created.")
    finally:
        Path(list_file).unlink(missing_ok=True)

    return output_path


# ---------------------------------------------------------------------------
# GUI (customtkinter + Pillow)
# ---------------------------------------------------------------------------

def launch_gui():
    try:
        import customtkinter as ctk
    except ImportError:
        print("customtkinter is required. Install: pip install customtkinter pillow")
        sys.exit(1)

    try:
        from PIL import Image
        HAS_PIL = True
    except ImportError:
        HAS_PIL = False

    VIDEO_TYPES = [
        ("Video files", "*.mp4 *.mov *.avi *.mkv *.wmv *.flv *.webm *.m4v"),
        ("All files", "*.*"),
    ]
    PREVIEW_W, PREVIEW_H = 540, 300

    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")

    # -----------------------------------------------------------------------
    class App(ctk.CTk):
        def __init__(self):
            super().__init__()
            self.title("Video Tools")
            self.resizable(False, False)
            self._saved_path = None
            self._stitch_saved = None
            self._build_ui()

        def _build_ui(self):
            self.tabs = ctk.CTkTabview(self, width=620)
            self.tabs.pack(padx=16, pady=16, fill="both", expand=True)

            self.tabs.add("Last Frame")
            self.tabs.add("Stitch Videos")

            self._build_last_frame_tab(self.tabs.tab("Last Frame"))
            self._build_stitch_tab(self.tabs.tab("Stitch Videos"))

        # -------------------------------------------------------------------
        # Tab 1 — Last Frame
        # -------------------------------------------------------------------
        def _build_last_frame_tab(self, tab):
            tab.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(tab, text="Video file:").grid(
                row=0, column=0, padx=(0, 8), pady=(12, 4), sticky="e"
            )
            self.video_var = ctk.StringVar()
            ctk.CTkEntry(tab, textvariable=self.video_var, width=400).grid(
                row=0, column=1, pady=(12, 4), sticky="ew"
            )
            ctk.CTkButton(tab, text="Browse…", width=90,
                          command=self._browse_video).grid(
                row=0, column=2, padx=(8, 0), pady=(12, 4)
            )

            self.lf_info_var = ctk.StringVar()
            ctk.CTkLabel(tab, textvariable=self.lf_info_var,
                         text_color="gray", anchor="w").grid(
                row=1, column=1, pady=(0, 4), sticky="w"
            )

            ctk.CTkLabel(tab, text="Output image:").grid(
                row=2, column=0, padx=(0, 8), pady=4, sticky="e"
            )
            self.output_var = ctk.StringVar()
            ctk.CTkEntry(tab, textvariable=self.output_var, width=400).grid(
                row=2, column=1, pady=4, sticky="ew"
            )
            ctk.CTkButton(tab, text="Browse…", width=90,
                          command=self._browse_lf_output).grid(
                row=2, column=2, padx=(8, 0), pady=4
            )

            ctk.CTkButton(tab, text="Extract Last Frame", height=38,
                          command=self._run_extract).grid(
                row=3, column=0, columnspan=3, pady=(10, 6)
            )

            if HAS_PIL:
                self.preview_label = ctk.CTkLabel(
                    tab,
                    text="Preview will appear here after extraction",
                    width=PREVIEW_W, height=PREVIEW_H,
                    fg_color=("gray88", "gray18"),
                    corner_radius=8,
                )
                self.preview_label.grid(
                    row=4, column=0, columnspan=3, pady=(0, 6)
                )

            self.lf_reveal_btn = ctk.CTkButton(
                tab, text="Reveal in Finder",
                fg_color="transparent", border_width=1,
                command=lambda: self._reveal(self._saved_path),
            )

            self.lf_status_var = ctk.StringVar(value="Ready.")
            ctk.CTkLabel(tab, textvariable=self.lf_status_var,
                         text_color="gray", anchor="w").grid(
                row=6, column=0, columnspan=3, pady=(0, 8), sticky="w"
            )

        def _browse_video(self):
            path = ctk.filedialog.askopenfilename(
                title="Select a video file", filetypes=VIDEO_TYPES
            )
            if not path:
                return
            self.video_var.set(path)
            if not self.output_var.get():
                p = Path(path)
                self.output_var.set(str(p.with_name(p.stem + "_last_frame.png")))
            try:
                info = get_video_info(path)
                w, h = info.get("width", "?"), info.get("height", "?")
                dur = info.get("duration")
                frames = info.get("nb_frames", "?")
                dur_str = f"{float(dur):.1f}s" if dur else "?"
                self.lf_info_var.set(f"{w}×{h}  ·  {dur_str}  ·  {frames} frames")
            except Exception:
                self.lf_info_var.set("")

        def _browse_lf_output(self):
            path = ctk.filedialog.asksaveasfilename(
                title="Save last frame as", defaultextension=".png",
                filetypes=[("PNG image", "*.png"), ("JPEG image", "*.jpg"),
                            ("All files", "*.*")]
            )
            if path:
                self.output_var.set(path)

        def _run_extract(self):
            video = self.video_var.get().strip()
            output = self.output_var.get().strip() or None
            if not video:
                ctk.messagebox.showwarning("No input", "Please select a video file first.")
                return
            self.lf_status_var.set("Extracting…")
            self.update_idletasks()
            try:
                saved = extract_last_frame(video, output)
                self._saved_path = saved
                self.lf_status_var.set(f"Saved: {saved}")
                if HAS_PIL:
                    self._show_preview(saved)
                self.lf_reveal_btn.grid(row=5, column=0, columnspan=3, pady=(0, 6))
            except Exception as exc:
                self.lf_status_var.set("Error.")
                ctk.messagebox.showerror("Error", str(exc))

        def _show_preview(self, path):
            try:
                img = Image.open(path)
                img.thumbnail((PREVIEW_W, PREVIEW_H), Image.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
                self.preview_label.configure(image=ctk_img, text="")
                self._preview_ref = ctk_img
            except Exception:
                pass

        # -------------------------------------------------------------------
        # Tab 2 — Stitch Videos
        # -------------------------------------------------------------------
        def _build_stitch_tab(self, tab):
            tab.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(tab, text="Videos to stitch (ordered top → bottom):",
                         anchor="w").grid(
                row=0, column=0, columnspan=2, padx=0, pady=(12, 4), sticky="w"
            )

            # Listbox via a scrollable frame
            self.stitch_list_frame = ctk.CTkScrollableFrame(
                tab, width=460, height=160, label_text=""
            )
            self.stitch_list_frame.grid(
                row=1, column=0, columnspan=2, pady=(0, 6), sticky="ew"
            )
            self.stitch_list_frame.grid_columnconfigure(0, weight=1)
            self._stitch_files: list[str] = []
            self._stitch_rows: list[ctk.CTkFrame] = []

            # Add / Clear buttons
            btn_row = ctk.CTkFrame(tab, fg_color="transparent")
            btn_row.grid(row=2, column=0, columnspan=2, pady=(0, 8), sticky="w")
            ctk.CTkButton(btn_row, text="+ Add Videos", width=120,
                          command=self._add_stitch_files).pack(side="left", padx=(0, 8))
            ctk.CTkButton(btn_row, text="Clear All", width=90,
                          fg_color="transparent", border_width=1,
                          command=self._clear_stitch_files).pack(side="left")

            # Output row
            ctk.CTkLabel(tab, text="Output video:").grid(
                row=3, column=0, pady=4, sticky="w"
            )
            out_row = ctk.CTkFrame(tab, fg_color="transparent")
            out_row.grid(row=4, column=0, columnspan=2, pady=(0, 6), sticky="ew")
            out_row.grid_columnconfigure(0, weight=1)
            self.stitch_output_var = ctk.StringVar()
            ctk.CTkEntry(out_row, textvariable=self.stitch_output_var).grid(
                row=0, column=0, sticky="ew", padx=(0, 8)
            )
            ctk.CTkButton(out_row, text="Browse…", width=90,
                          command=self._browse_stitch_output).grid(row=0, column=1)

            # Re-encode toggle
            self.reencode_var = ctk.BooleanVar(value=False)
            ctk.CTkCheckBox(
                tab,
                text="Re-encode (slower — use if videos have different formats/resolutions)",
                variable=self.reencode_var,
            ).grid(row=5, column=0, columnspan=2, pady=(0, 8), sticky="w")

            ctk.CTkButton(tab, text="Stitch Videos", height=38,
                          command=self._run_stitch).grid(
                row=6, column=0, columnspan=2, pady=(0, 8)
            )

            self.stitch_reveal_btn = ctk.CTkButton(
                tab, text="Reveal in Finder",
                fg_color="transparent", border_width=1,
                command=lambda: self._reveal(self._stitch_saved),
            )

            self.stitch_status_var = ctk.StringVar(value="Ready.")
            ctk.CTkLabel(tab, textvariable=self.stitch_status_var,
                         text_color="gray", anchor="w").grid(
                row=8, column=0, columnspan=2, pady=(0, 8), sticky="w"
            )

        def _add_stitch_files(self):
            paths = ctk.filedialog.askopenfilenames(
                title="Select videos to stitch", filetypes=VIDEO_TYPES
            )
            for p in paths:
                if p not in self._stitch_files:
                    self._stitch_files.append(p)
            self._refresh_stitch_list()

        def _clear_stitch_files(self):
            self._stitch_files.clear()
            self._refresh_stitch_list()

        def _refresh_stitch_list(self):
            for row in self._stitch_rows:
                row.destroy()
            self._stitch_rows.clear()

            for idx, path in enumerate(self._stitch_files):
                frame = ctk.CTkFrame(self.stitch_list_frame, fg_color="transparent")
                frame.grid(row=idx, column=0, sticky="ew", pady=2)
                frame.grid_columnconfigure(1, weight=1)

                # Up / Down arrows
                ctk.CTkButton(
                    frame, text="↑", width=28, height=24,
                    command=lambda i=idx: self._move_stitch(i, -1)
                ).grid(row=0, column=0, padx=(0, 2))
                ctk.CTkButton(
                    frame, text="↓", width=28, height=24,
                    command=lambda i=idx: self._move_stitch(i, 1)
                ).grid(row=0, column=1, padx=(0, 6))

                ctk.CTkLabel(
                    frame, text=Path(path).name, anchor="w"
                ).grid(row=0, column=2, sticky="ew")

                ctk.CTkButton(
                    frame, text="✕", width=28, height=24,
                    fg_color="transparent", border_width=1,
                    command=lambda i=idx: self._remove_stitch(i)
                ).grid(row=0, column=3, padx=(6, 0))

                self._stitch_rows.append(frame)

        def _move_stitch(self, idx, direction):
            new_idx = idx + direction
            if 0 <= new_idx < len(self._stitch_files):
                self._stitch_files[idx], self._stitch_files[new_idx] = \
                    self._stitch_files[new_idx], self._stitch_files[idx]
                self._refresh_stitch_list()

        def _remove_stitch(self, idx):
            self._stitch_files.pop(idx)
            self._refresh_stitch_list()

        def _browse_stitch_output(self):
            path = ctk.filedialog.asksaveasfilename(
                title="Save stitched video as",
                defaultextension=".mp4",
                filetypes=[("MP4 video", "*.mp4"), ("MOV video", "*.mov"),
                            ("All files", "*.*")],
            )
            if path:
                self.stitch_output_var.set(path)

        def _run_stitch(self):
            if len(self._stitch_files) < 2:
                ctk.messagebox.showwarning(
                    "Not enough videos", "Add at least 2 videos to stitch."
                )
                return
            output = self.stitch_output_var.get().strip()
            if not output:
                ctk.messagebox.showwarning(
                    "No output path", "Please choose an output file path."
                )
                return
            self.stitch_status_var.set("Stitching…")
            self.update_idletasks()
            try:
                saved = stitch_videos(
                    self._stitch_files, output,
                    re_encode=self.reencode_var.get()
                )
                self._stitch_saved = saved
                self.stitch_status_var.set(f"Saved: {saved}")
                self.stitch_reveal_btn.grid(row=7, column=0, columnspan=2, pady=(0, 6))
            except Exception as exc:
                self.stitch_status_var.set("Error.")
                ctk.messagebox.showerror("Error", str(exc))

        # -------------------------------------------------------------------
        def _reveal(self, path):
            if path:
                subprocess.run(["open", "-R", path])

    App().mainloop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract the last frame from a video file.",
        epilog="Run without arguments to open the GUI.",
    )
    parser.add_argument("video", nargs="?", help="Path to the input video file")
    parser.add_argument(
        "-o", "--output",
        help="Output image path (default: <video_name>_last_frame.png alongside the video)",
        default=None,
    )
    args = parser.parse_args()

    if args.video:
        try:
            saved = extract_last_frame(args.video, args.output)
            print(f"Last frame saved to: {saved}")
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        launch_gui()


if __name__ == "__main__":
    main()
