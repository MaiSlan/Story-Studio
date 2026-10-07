"""Story "tracks" (what the learner is practising) and all the knobs of a request.

A *track* decides which language is the main practice line:

  pinyin  -> pinyin (bold, read aloud) + simplified hanzi (grey) + English (small italic)
  french  -> French (bold)             + simplified hanzi (grey) + English (small italic)

Every story line is therefore three strings: primary / hanzi / english.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Track:
    id: str
    label: str
    primary_name: str          # name of the primary field in the JSON the AI returns
    primary_label: str         # human label used in the UI and the PDF subtitle
    pdf_subtitle: str
    levels: dict[int, str]     # level -> description injected into the prompt


TRACKS: dict[str, Track] = {
    "pinyin": Track(
        id="pinyin",
        label="Pinyin reading (for Mandarin learners)",
        primary_name="pinyin",
        primary_label="Pinyin",
        pdf_subtitle="Pinyin reading practice",
        levels={
            1: "Level 1 (absolute beginner, about HSK 1): only the most common ~150 words; sentences of 3-8 characters; "
               "very repetitive; present-tense and simple past with 了; no idioms.",
            2: "Level 2 (about HSK 2): ~300 common words; sentences of 4-10 characters; simple connectors "
               "(因为, 所以, 但是, 然后); occasional 把 sentences.",
            3: "Level 3 (about HSK 3): ~600 words; sentences of 5-14 characters; 把/被 sentences, 着/过, "
               "comparisons; a few easy four-character expressions.",
            4: "Level 4 (about HSK 3-4): ~1000 words; sentences of 6-18 characters; richer description; "
               "a handful of well-known chengyu, each clear from context.",
            5: "Level 5 (about HSK 4): ~1500 words; sentences up to ~22 characters; literary touches, "
               "more chengyu, but still no rare characters.",
        },
    ),
    "french": Track(
        id="french",
        label="French reading (for French learners)",
        primary_name="french",
        primary_label="Français",
        pdf_subtitle="Lecture en français",
        levels={
            1: "Level 1 (CEFR A1): present tense, a few passé composé forms, futur proche; sentences of 4-9 words; "
               "most frequent ~500 words; repeat key words often.",
            2: "Level 2 (CEFR A2): passé composé and imparfait in simple use; sentences of 5-12 words; "
               "~1000 common words; simple connectors (mais, parce que, alors, puis).",
            3: "Level 3 (CEFR A2+/B1-): passé composé/imparfait contrasts, futur simple, pronouns y/en; "
               "sentences of 6-15 words; ~1500 words.",
            4: "Level 4 (CEFR B1): plus-que-parfait, conditionnel, direct and indirect speech; sentences of 8-18 words; "
               "~2000 words, a few idioms.",
            5: "Level 5 (CEFR B1+): subjonctif in common constructions, passé simple allowed sparingly in "
               "historical/fairy-tale register; ~2500 words; sentences up to ~22 words.",
        },
    ),
}

# Lines per story. A "line" is one numbered triple (primary + hanzi + English).
LENGTHS: dict[str, dict] = {
    "short": {"label": "Short (about 50 lines)", "lines": 50},
    "medium": {"label": "Medium (about 130 lines, range 100-150)", "lines": 130},
    "long": {"label": "Long (about 200 lines, 150+)", "lines": 200},
    "custom": {"label": "Custom number of lines", "lines": None},
}
MIN_LINES, MAX_LINES = 10, 600

# `voice` and `source_mode` are defined in style/voices.md and style/source_modes.md
# (plain text you can edit). These are just the allowed ids and UI labels.
VOICES: dict[str, str] = {
    "auto": "Let the AI choose",
    "ancient_tale": "Ancient tale: poetic, minimal, a few sharp lines",
    "storyteller": "Warm storyteller: lively, dialogue, light humour",
    "chronicle": "Chronicle: clear history-telling, accurate events",
    "fairytale": "Fairy tale: classic cadence, repetition, rule of three",
    "faithful": "Faithful retelling: follows the source's own style and plot",
}

SOURCE_MODES: dict[str, str] = {
    "auto": "Let the AI decide (applies your IP rules)",
    "original": "Original story on my topic",
    "myth": "Myth / legend / folklore (full creative freedom)",
    "lore_only": "Big-picture lore only (licensed worlds: games, films, series)",
    "adaptation": "Simplified retelling of a book (follows its plot, own words)",
}

LINES_PER_CHUNK = 25
