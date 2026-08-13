#!/usr/bin/env python3

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote


# =============================================================================
# CONFIGURATION
# =============================================================================

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_FIGURES_DIR = ROOT / "figures"
DEFAULT_OUTPUT_DIR = ROOT / "docs"

PNG_DPI = 200


# =============================================================================
# METADATA
# =============================================================================

def read_metadata(tex_file: Path) -> dict:
    """
    Read metadata from comments at the beginning of a .tex file.

    Example:

        % gallery-title: Magic-state distillation
        % gallery-category: Quantum computing
        % gallery-tags: magic states, fault tolerance
        % gallery-description: A magic-state distillation protocol.
        % gallery-order: 10
        % gallery-ignore: false
    """

    metadata = {}

    with tex_file.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            stripped = line.strip()

            # Empty lines at the beginning are allowed
            if not stripped:
                continue

            # Stop parsing metadata once actual LaTeX starts
            if not stripped.startswith("%"):
                break

            match = re.match(
                r"%\s*gallery-([\w-]+)\s*:\s*(.*)",
                stripped,
                flags=re.IGNORECASE,
            )

            if match:
                key, value = match.groups()
                metadata[key.lower()] = value.strip()

    return metadata


def parse_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default

    return value.strip().lower() in {
        "true",
        "yes",
        "1",
        "on",
    }


def parse_order(value: str | None) -> int:
    if value is None:
        return 999999

    try:
        return int(value)
    except ValueError:
        return 999999


# =============================================================================
# TEX FILE HANDLING
# =============================================================================

def is_standalone_tex(tex_file: Path) -> bool:
    """
    Return True only for files that look like complete LaTeX documents.

    This prevents files included using \\input or \\include from being treated
    as independent figures.
    """

    text = tex_file.read_text(
        encoding="utf-8",
        errors="ignore",
    )

    return r"\documentclass" in text


def detect_latex_engine(tex_file: Path) -> str:
    """
    Detect a TeX engine from common editor directives.

    Otherwise use pdflatex.
    """

    text = tex_file.read_text(
        encoding="utf-8",
        errors="ignore",
    ).lower()

    if re.search(r"%\s*!tex\s+program\s*=\s*lualatex", text):
        return "-lualatex"

    if re.search(r"%\s*!tex\s+program\s*=\s*xelatex", text):
        return "-xelatex"

    return "-pdf"


def slugify(tex_file: Path, figures_dir: Path) -> str:
    """
    Produce a unique filename from the path.

    Example:

        figures/quantum/gate_teleportation.tex

    becomes:

        quantum-gate_teleportation
    """

    relative = tex_file.relative_to(figures_dir).with_suffix("")

    slug = str(relative).replace(os.sep, "-")

    slug = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "-",
        slug,
    )

    slug = slug.strip("-")

    return slug


# =============================================================================
# GITHUB INFORMATION
# =============================================================================

def run_git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
    ):
        return None


def detect_github_repository() -> str | None:
    """
    Try to detect

        username/repository

    from the origin remote.
    """

    remote = run_git(
        "remote",
        "get-url",
        "origin",
    )

    if not remote:
        return None

    patterns = [
        r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$",
    ]

    for pattern in patterns:
        match = re.search(pattern, remote)

        if match:
            user, repository = match.groups()
            repository = re.sub(r"\.git$", "", repository)

            return f"{user}/{repository}"

    return None


def detect_git_branch() -> str:
    branch = run_git(
        "branch",
        "--show-current",
    )

    return branch or "main"


def github_source_url(
    repository: str | None,
    branch: str,
    relative_path: Path,
) -> str | None:

    if not repository:
        return None

    encoded_path = quote(
        relative_path.as_posix(),
        safe="/",
    )

    encoded_branch = quote(
        branch,
        safe="",
    )

    return (
        f"https://github.com/{repository}"
        f"/blob/{encoded_branch}/{encoded_path}"
    )


# =============================================================================
# COMPILATION
# =============================================================================

def compile_figure(
    tex_file: Path,
    figures_dir: Path,
    output_dir: Path,
) -> dict:

    metadata = read_metadata(tex_file)

    slug = slugify(
        tex_file,
        figures_dir,
    )

    pdf_dir = output_dir / "pdf"
    image_dir = output_dir / "images"

    pdf_destination = pdf_dir / f"{slug}.pdf"
    png_destination = image_dir / f"{slug}.png"

    engine = detect_latex_engine(tex_file)

    print(
        f"  [{engine.lstrip('-')}] "
        f"{tex_file.relative_to(ROOT)}"
    )

    with tempfile.TemporaryDirectory() as tmp_dir:

        tmp_dir = Path(tmp_dir)

        command = [
            "latexmk",
            engine,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            f"-outdir={tmp_dir}",
            tex_file.name,
        ]

        subprocess.run(
            command,
            cwd=tex_file.parent,
            check=True,
        )

        generated_pdf = (
            tmp_dir / f"{tex_file.stem}.pdf"
        )

        if not generated_pdf.exists():
            raise RuntimeError(
                f"LaTeX compilation succeeded but no PDF was produced: "
                f"{tex_file}"
            )

        shutil.copy2(
            generated_pdf,
            pdf_destination,
        )

        # Convert first PDF page to PNG
        subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-singlefile",
                "-f",
                "1",
                "-r",
                str(PNG_DPI),
                str(generated_pdf),
                str(png_destination.with_suffix("")),
            ],
            check=True,
        )

    title = metadata.get(
        "title",
        tex_file.stem
        .replace("_", " ")
        .replace("-", " ")
        .title(),
    )

    category = metadata.get(
        "category",
        "Other",
    )

    description = metadata.get(
        "description",
        "",
    )

    tags = [
        tag.strip()
        for tag in metadata.get(
            "tags",
            "",
        ).split(",")
        if tag.strip()
    ]

    order = parse_order(
        metadata.get("order")
    )

    return {
        "title": title,
        "category": category,
        "description": description,
        "tags": tags,
        "order": order,
        "slug": slug,
        "source_path": tex_file.relative_to(ROOT),
        "pdf": f"pdf/{slug}.pdf",
        "png": f"images/{slug}.png",
    }


# =============================================================================
# HTML GENERATION
# =============================================================================

def make_card(
    figure: dict,
    repository: str | None,
    branch: str,
) -> str:

    title = html.escape(
        figure["title"]
    )

    category = html.escape(
        figure["category"]
    )

    description = html.escape(
        figure["description"]
    )

    tags = figure["tags"]

    source_url = github_source_url(
        repository,
        branch,
        figure["source_path"],
    )

    if source_url:
        source_button = f"""
            <a
                class="button"
                href="{html.escape(source_url)}"
                target="_blank"
                rel="noopener"
            >
                LaTeX source
            </a>
        """
    else:
        source_button = ""

    if tags:
        tag_html = "".join(
            f'<span class="tag">{html.escape(tag)}</span>'
            for tag in tags
        )

        tags_section = f"""
            <div class="tags">
                {tag_html}
            </div>
        """
    else:
        tags_section = ""

    if description:
        description_section = f"""
            <p class="description">
                {description}
            </p>
        """
    else:
        description_section = ""

    search_text = " ".join(
        [
            figure["title"],
            figure["category"],
            figure["description"],
            *tags,
        ]
    ).lower()

    search_text = html.escape(
        search_text,
        quote=True,
    )

    category_attribute = html.escape(
        figure["category"],
        quote=True,
    )

    return f"""
    <article
        class="card"
        data-category="{category_attribute}"
        data-search="{search_text}"
    >

        <a
            class="preview-link"
            href="{html.escape(figure['pdf'])}"
            target="_blank"
        >
            <div class="preview">

                <img
                    src="{html.escape(figure['png'])}"
                    alt="{title}"
                    loading="lazy"
                >

            </div>
        </a>

        <div class="card-body">

            <div class="category">
                {category}
            </div>

            <h2>
                {title}
            </h2>

            {description_section}

            {tags_section}

            <div class="buttons">

                {source_button}

                <a
                    class="button"
                    href="{html.escape(figure['pdf'])}"
                    target="_blank"
                >
                    PDF
                </a>

                <a
                    class="button"
                    href="{html.escape(figure['png'])}"
                    target="_blank"
                >
                    PNG
                </a>

            </div>

        </div>

    </article>
    """


def build_html(
    figures: list[dict],
    repository: str | None,
    branch: str,
) -> str:

    categories = sorted(
        {
            figure["category"]
            for figure in figures
        },
        key=str.lower,
    )

    cards = "\n".join(
        make_card(
            figure,
            repository,
            branch,
        )
        for figure in figures
    )

    category_buttons = "\n".join(
        f"""
        <button
            class="filter-button"
            data-category="{html.escape(category, quote=True)}"
        >
            {html.escape(category)}
        </button>
        """
        for category in categories
    )

    repository_link = ""

    if repository:
        repository_link = f"""
        <a
            class="repository-link"
            href="https://github.com/{html.escape(repository)}"
            target="_blank"
            rel="noopener"
        >
            View repository on GitHub
        </a>
        """

    return f"""<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1"
>

<title>LaTeX Figure Gallery</title>

<style>

:root {{
    --background: #f8f9fa;
    --card-background: #ffffff;
    --text: #1f2937;
    --muted: #6b7280;
    --border: #e5e7eb;
    --accent: #2563eb;
    --accent-light: #eff6ff;
}}

* {{
    box-sizing: border-box;
}}

body {{
    margin: 0;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Helvetica,
        Arial,
        sans-serif;

    background: var(--background);
    color: var(--text);
}}

header {{
    max-width: 1500px;
    margin: auto;

    padding:
        60px
        32px
        25px;
}}

header h1 {{
    margin: 0 0 10px;

    font-size: clamp(
        2rem,
        5vw,
        3rem
    );

    letter-spacing: -0.03em;
}}

.subtitle {{
    margin: 0;

    color: var(--muted);

    font-size: 1.05rem;
}}

.repository-link {{
    display: inline-block;

    margin-top: 14px;

    color: var(--accent);

    text-decoration: none;
}}

.repository-link:hover {{
    text-decoration: underline;
}}

.controls {{
    max-width: 1500px;
    margin: auto;

    padding:
        10px
        32px
        25px;
}}

.search {{
    width: 100%;
    max-width: 650px;

    padding:
        13px
        16px;

    font-size: 1rem;

    color: var(--text);

    background: white;

    border:
        1px
        solid
        var(--border);

    border-radius: 8px;

    outline: none;
}}

.search:focus {{
    border-color: var(--accent);
}}

.filters {{
    display: flex;
    flex-wrap: wrap;

    gap: 8px;

    margin-top: 15px;
}}

.filter-button {{
    padding:
        8px
        13px;

    cursor: pointer;

    background: white;

    border:
        1px
        solid
        var(--border);

    border-radius: 20px;

    color: var(--text);

    font-size: 0.9rem;
}}

.filter-button:hover,
.filter-button.active {{
    background: var(--accent);
    border-color: var(--accent);
    color: white;
}}

.gallery {{
    max-width: 1500px;
    margin: auto;

    padding:
        10px
        32px
        80px;

    display: grid;

    grid-template-columns:
        repeat(
            auto-fill,
            minmax(300px, 1fr)
        );

    gap: 24px;
}}

.card {{
    display: flex;
    flex-direction: column;

    background: var(--card-background);

    border:
        1px
        solid
        var(--border);

    border-radius: 12px;

    overflow: hidden;

    transition:
        transform 0.15s ease,
        box-shadow 0.15s ease;
}}

.card:hover {{
    transform: translateY(-2px);

    box-shadow:
        0
        6px
        20px
        rgb(0 0 0 / 7%);
}}

.card.hidden {{
    display: none;
}}

.preview-link {{
    text-decoration: none;
}}

.preview {{
    height: 300px;

    padding: 25px;

    display: flex;
    align-items: center;
    justify-content: center;

    background: white;

    border-bottom:
        1px
        solid
        var(--border);
}}

.preview img {{
    max-width: 100%;
    max-height: 100%;

    object-fit: contain;
}}

.card-body {{
    padding: 20px;
}}

.category {{
    margin-bottom: 7px;

    color: var(--accent);

    font-size: 0.78rem;

    font-weight: 600;

    text-transform: uppercase;

    letter-spacing: 0.04em;
}}

.card h2 {{
    margin:
        0
        0
        10px;

    font-size: 1.15rem;
}}

.description {{
    margin:
        0
        0
        15px;

    color: var(--muted);

    line-height: 1.5;

    font-size: 0.92rem;
}}

.tags {{
    display: flex;
    flex-wrap: wrap;

    gap: 6px;

    margin-bottom: 17px;
}}

.tag {{
    padding:
        4px
        8px;

    background: var(--accent-light);

    color: var(--accent);

    border-radius: 5px;

    font-size: 0.75rem;
}}

.buttons {{
    display: flex;
    flex-wrap: wrap;

    gap: 13px;

    margin-top: 5px;
}}

.button {{
    color: var(--accent);

    text-decoration: none;

    font-size: 0.88rem;

    font-weight: 500;
}}

.button:hover {{
    text-decoration: underline;
}}

.no-results {{
    display: none;

    max-width: 1500px;
    margin: auto;

    padding:
        20px
        32px
        80px;

    color: var(--muted);
}}

footer {{
    padding:
        30px
        20px;

    text-align: center;

    color: var(--muted);

    font-size: 0.8rem;
}}

@media (max-width: 600px) {{

    header,
    .controls,
    .gallery {{
        padding-left: 18px;
        padding-right: 18px;
    }}

    .gallery {{
        grid-template-columns: 1fr;
    }}

    .preview {{
        height: 260px;
    }}

}}

</style>

</head>

<body>

<header>

    <h1>
        LaTeX Figure Gallery
    </h1>

    <p class="subtitle">
        {len(figures)} figures made with LaTeX, TikZ and related packages.
    </p>

    {repository_link}

</header>


<section class="controls">

    <input
        id="search"
        class="search"
        type="search"
        placeholder="Search figures..."
        autocomplete="off"
    >

    <div class="filters">

        <button
            class="filter-button active"
            data-category="all"
        >
            All
        </button>

        {category_buttons}

    </div>

</section>


<main
    id="gallery"
    class="gallery"
>

    {cards}

</main>


<div
    id="no-results"
    class="no-results"
>
    No figures found.
</div>


<footer>
    Generated automatically from the LaTeX source files.
</footer>


<script>

const cards =
    Array.from(
        document.querySelectorAll(".card")
    );

const searchInput =
    document.getElementById("search");

const filterButtons =
    document.querySelectorAll(".filter-button");

const noResults =
    document.getElementById("no-results");

let activeCategory = "all";


function updateGallery() {{

    const query =
        searchInput.value
            .trim()
            .toLowerCase();

    let visible = 0;

    cards.forEach(card => {{

        const category =
            card.dataset.category;

        const searchText =
            card.dataset.search;

        const matchesCategory =
            activeCategory === "all"
            || category === activeCategory;

        const matchesSearch =
            searchText.includes(query);

        const show =
            matchesCategory
            && matchesSearch;

        card.classList.toggle(
            "hidden",
            !show
        );

        if (show) {{
            visible += 1;
        }}

    }});

    noResults.style.display =
        visible === 0
            ? "block"
            : "none";
}}


searchInput.addEventListener(
    "input",
    updateGallery
);


filterButtons.forEach(button => {{

    button.addEventListener(
        "click",
        () => {{

            activeCategory =
                button.dataset.category;

            filterButtons.forEach(b =>
                b.classList.remove("active")
            );

            button.classList.add("active");

            updateGallery();

        }}
    );

}});

</script>

</body>

</html>
"""


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "Compile LaTeX figures and build "
            "a static HTML gallery."
        )
    )

    parser.add_argument(
        "--figures",
        type=Path,
        default=DEFAULT_FIGURES_DIR,
        help="Directory containing the LaTeX figures.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory in which to generate the website.",
    )

    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete the output directory before building.",
    )

    args = parser.parse_args()

    figures_dir = args.figures.resolve()
    output_dir = args.output.resolve()

    if not figures_dir.exists():
        print(
            f"Figures directory does not exist: "
            f"{figures_dir}",
            file=sys.stderr,
        )
        return 1

    # -------------------------------------------------------------------------
    # Check dependencies
    # -------------------------------------------------------------------------

    required_commands = [
        "latexmk",
        "pdftoppm",
    ]

    missing = [
        command
        for command in required_commands
        if shutil.which(command) is None
    ]

    if missing:
        print(
            "Missing required programs:",
            ", ".join(missing),
            file=sys.stderr,
        )

        return 1

    # -------------------------------------------------------------------------
    # Prepare output directory
    # -------------------------------------------------------------------------

    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)

    (output_dir / "images").mkdir(
        parents=True,
        exist_ok=True,
    )

    (output_dir / "pdf").mkdir(
        parents=True,
        exist_ok=True,
    )

    # -------------------------------------------------------------------------
    # Find figures
    # -------------------------------------------------------------------------

    tex_files = []

    for tex_file in sorted(
        figures_dir.rglob("*.tex")
    ):

        if not is_standalone_tex(tex_file):
            continue

        metadata = read_metadata(tex_file)

        if parse_bool(
            metadata.get("ignore"),
            default=False,
        ):
            print(
                "  [skip] "
                f"{tex_file.relative_to(ROOT)}"
            )

            continue

        tex_files.append(tex_file)

    print()
    print(
        f"Found {len(tex_files)} "
        f"standalone figures."
    )
    print()

    # -------------------------------------------------------------------------
    # Compile
    # -------------------------------------------------------------------------

    figures = []
    errors = []

    for tex_file in tex_files:

        try:
            figure = compile_figure(
                tex_file,
                figures_dir,
                output_dir,
            )

            figures.append(figure)

        except Exception as error:

            errors.append(
                (
                    tex_file,
                    error,
                )
            )

            print()
            print(
                "ERROR:"
            )

            print(
                f"  {tex_file.relative_to(ROOT)}"
            )

            print(
                f"  {error}"
            )

            print()

    # -------------------------------------------------------------------------
    # Sort
    # -------------------------------------------------------------------------

    figures.sort(
        key=lambda fig: (
            fig["order"],
            fig["category"].lower(),
            fig["title"].lower(),
        )
    )

    # -------------------------------------------------------------------------
    # Git information
    # -------------------------------------------------------------------------

    repository = (
        detect_github_repository()
    )

    branch = detect_git_branch()

    if repository:
        print()
        print(
            f"GitHub repository: "
            f"{repository}"
        )

        print(
            f"Git branch: "
            f"{branch}"
        )

    else:
        print()
        print(
            "Warning: could not detect a "
            "GitHub remote."
        )

        print(
            "LaTeX source buttons will "
            "not be displayed."
        )

    # -------------------------------------------------------------------------
    # Generate site
    # -------------------------------------------------------------------------

    page = build_html(
        figures,
        repository,
        branch,
    )

    index_file = (
        output_dir / "index.html"
    )

    index_file.write_text(
        page,
        encoding="utf-8",
    )

    # Tell GitHub Pages not to run Jekyll
    (output_dir / ".nojekyll").touch()

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------

    print()
    print("=" * 60)

    print(
        f"Generated gallery: "
        f"{index_file}"
    )

    print(
        f"Figures generated: "
        f"{len(figures)}"
    )

    if errors:

        print(
            f"Compilation errors: "
            f"{len(errors)}"
        )

        print()

        for tex_file, error in errors:

            print(
                " - "
                f"{tex_file.relative_to(ROOT)}"
            )

        return 1

    print(
        "All figures compiled successfully."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())