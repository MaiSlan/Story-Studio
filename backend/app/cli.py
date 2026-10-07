"""Command-line access to the same engine:  python -m app.cli --help"""
from __future__ import annotations

import argparse
import sys

from .config import PROVIDERS, default_provider_id
from .generator import generate_ideas, generate_story
from .models import StoryRequest
from .pdf import render_pdf
from .providers import LLMError, get_provider
from .storage import list_stories, load_story, slugify
from .tracks import LENGTHS, SOURCE_MODES, TRACKS, VOICES
from .validate import validate_story


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="story-studio")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("providers", help="show which AI providers have a key")
    sub.add_parser("list", help="list saved stories")

    g = sub.add_parser("generate", help="write a story (and a PDF next to it)")
    g.add_argument("--track", choices=TRACKS, default="pinyin")
    g.add_argument("--topic", required=True)
    g.add_argument("--length", choices=LENGTHS, default="medium")
    g.add_argument("--lines", type=int, help="with --length custom")
    g.add_argument("--level", type=int, default=2, choices=range(1, 6))
    g.add_argument("--voice", choices=VOICES, default="auto")
    g.add_argument("--source", choices=SOURCE_MODES, default="auto")
    g.add_argument("--notes", default="")
    g.add_argument("--provider", default=default_provider_id())
    g.add_argument("--model")
    g.add_argument("--pdf", action="store_true", help="also write the PDF into the current folder")

    i = sub.add_parser("ideas", help="ask the AI for story ideas")
    i.add_argument("--track", choices=TRACKS, default="pinyin")
    i.add_argument("--theme", default="")
    i.add_argument("--provider", default=default_provider_id())
    i.add_argument("--model")

    p = sub.add_parser("pdf", help="render a saved story to PDF")
    p.add_argument("story_id")
    p.add_argument("-o", "--output")

    c = sub.add_parser("check", help="run the pinyin/hanzi checks on a saved story")
    c.add_argument("story_id")

    a = ap.parse_args(argv)
    try:
        if a.cmd == "providers":
            for p_ in PROVIDERS.values():
                print(f"{p_.id:11} {'ready ' if p_.configured() else 'no key'}  {p_.label}  [{p_.model()}]")
        elif a.cmd == "list":
            for s in list_stories():
                print(f"{s['id']:48} {s['track']:6} L{s['level']} {s['lines']:4} lines  {s['title'].get('english', '')}")
        elif a.cmd == "generate":
            req = StoryRequest(track=a.track, topic=a.topic, length=a.length, custom_lines=a.lines, level=a.level,
                               voice=a.voice, source_mode=a.source, notes=a.notes, provider=a.provider, model=a.model)
            story = generate_story(req, get_provider(a.provider, a.model),
                                   progress=lambda p_: print(f"  {p_['message']} ({p_['done_lines']}/{p_['total_lines']})", file=sys.stderr))
            print(f"Saved {story.id} ({len(story.lines)} lines, {story.usage.get('output_tokens', 0)} output tokens)")
            if a.pdf:
                out = f"{slugify(story.title.english)}.pdf"
                open(out, "wb").write(render_pdf(story))
                print("PDF:", out)
        elif a.cmd == "ideas":
            for idea in generate_ideas(a.track, a.theme, 8, get_provider(a.provider, a.model), [s["title"].get("english", "") for s in list_stories()]):
                print(f"- {idea['title']} [{idea['source_mode']}/{idea['voice']}]\n    {idea['pitch']}")
        elif a.cmd == "pdf":
            story = load_story(a.story_id)
            out = a.output or f"{slugify(story.title.english or story.id)}.pdf"
            open(out, "wb").write(render_pdf(story))
            print("PDF:", out)
        elif a.cmd == "check":
            s = load_story(a.story_id)
            names = [(x["hanzi"], x["primary"]) for x in s.characters]
            rep = validate_story(s.track, [l.model_dump() for l in s.lines], names, s.target_lines)
            print(f"{rep['errors']} errors, {rep['warnings']} notes")
            for n, issues in rep["lines"].items():
                for it in issues:
                    print(f"  line {n}: [{it['level']}] {it['msg']}")
            return 1 if rep["errors"] else 0
    except (LLMError, KeyError) as exc:
        print("Error:", exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
