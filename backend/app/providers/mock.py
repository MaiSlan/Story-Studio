"""Offline demo provider: no AI, no key, no cost. It returns canned (nonsense) stories in the exact
JSON shape a real model must return, so you can try the app, the PDF and the editor immediately,
and so the test-suite can run without network access."""
from __future__ import annotations

import json
import re
import time

from ..pinyin_tools import pinyin_from_hanzi
from .base import LLMResult, Provider

ZH_BANK = [
    ("很久以前，山上有一只小猴子。", "Long ago, there was a little monkey on the mountain."),
    ("他每天看着天上的云。", "Every day he watched the clouds in the sky."),
    ("“云的后面有什么？”他问。", "“What is behind the clouds?” he asked."),
    ("没有人能回答他。", "Nobody could answer him."),
    ("于是，他决定自己去看看。", "So he decided to go and see for himself."),
    ("他走了很远很远的路。", "He walked a very, very long way."),
    ("河水很凉，风也很大。", "The river was cold and the wind was strong."),
    ("一位老人坐在大石头上。", "An old man sat on a big stone."),
    ("老人笑着说：“你要去哪里？”", "Smiling, the old man said, “Where are you going?”"),
    ("“我想去云的后面。”", "“I want to go behind the clouds.”"),
    ("老人给了他一个红苹果。", "The old man gave him a red apple."),
    ("小猴子说了谢谢，又往前走。", "The little monkey said thank you and walked on."),
    ("天黑了，月亮出来了。", "Night fell and the moon came out."),
    ("他躺在草地上，看着星星。", "He lay on the grass and looked at the stars."),
    ("早上，他看见了一座高山。", "In the morning he saw a tall mountain."),
    ("山很高，云就在山顶。", "The mountain was tall, and the clouds were on its top."),
    ("他一步一步地往上爬。", "He climbed up, step by step."),
    ("手很疼，脚也很累。", "His hands hurt and his feet were tired."),
    ("可是他没有停下来。", "But he did not stop."),
    ("终于，他到了山顶。", "At last he reached the top."),
    ("云就在他的身边。", "The clouds were right beside him."),
    ("原来云是软软的、凉凉的。", "So clouds were soft and cool."),
    ("他笑了，因为他看见了整个世界。", "He laughed, because he could see the whole world."),
    ("山下的小河像一条银线。", "The little river below was like a silver thread."),
]

FR_BANK = [
    ("Il était une fois un petit renard.", "从前，有一只小狐狸。", "Once upon a time, there was a little fox."),
    ("Il vivait au bord d’une grande forêt.", "他住在一片大森林的边上。", "He lived at the edge of a big forest."),
    ("Chaque matin, il regardait le soleil.", "每天早上，他都看着太阳。", "Every morning he looked at the sun."),
    ("— Où va le soleil la nuit ? demanda-t-il.", "“太阳晚上去哪里？”他问。", "“Where does the sun go at night?” he asked."),
    ("Personne ne savait répondre.", "没有人知道答案。", "Nobody knew the answer."),
    ("Alors, il décida de partir.", "于是，他决定出发。", "So he decided to leave."),
    ("Il marcha longtemps le long de la rivière.", "他沿着河走了很久。", "He walked for a long time along the river."),
    ("Un vieux hibou était assis sur une branche.", "一只老猫头鹰坐在树枝上。", "An old owl was sitting on a branch."),
    ("— Où vas-tu, petit renard ?", "“小狐狸，你要去哪里？”", "“Where are you going, little fox?”"),
    ("— Je cherche la maison du soleil.", "“我在找太阳的家。”", "“I am looking for the sun’s house.”"),
    ("Le hibou sourit et lui donna une pomme.", "猫头鹰笑了笑，给了他一个苹果。", "The owl smiled and gave him an apple."),
    ("Le renard dit merci et continua sa route.", "狐狸说了谢谢，继续赶路。", "The fox said thank you and went on."),
    ("La nuit tomba et la lune apparut.", "天黑了，月亮出来了。", "Night fell and the moon appeared."),
    ("Il s’endormit sur l’herbe fraîche.", "他睡在凉凉的草地上。", "He fell asleep on the cool grass."),
    ("Le matin, il vit une haute montagne.", "早上，他看见了一座高山。", "In the morning he saw a high mountain."),
    ("Il monta, pas à pas, jusqu’au sommet.", "他一步一步地爬到了山顶。", "He climbed, step by step, to the top."),
    ("De là-haut, il vit le soleil se coucher.", "在山顶，他看见太阳落下去。", "From up there, he saw the sun go down."),
    ("Le soleil n’avait pas de maison.", "太阳没有家。", "The sun had no house."),
    ("Il dormait dans le ciel, avec les étoiles.", "它和星星一起睡在天上。", "It slept in the sky, with the stars."),
    ("Le petit renard rentra chez lui, heureux.", "小狐狸高高兴兴地回家了。", "The little fox went home, happy."),
]


def _field(text: str, key: str, default: int = 0) -> int:
    m = re.search(rf"^{key}:\s*(\d+)", text, flags=re.M)
    return int(m.group(1)) if m else default


class MockProvider(Provider):
    def complete(self, system, user, *, max_tokens=4096, temperature=0.8, json_mode=True) -> LLMResult:
        time.sleep(0.35)  # so progress is visible in the UI
        task = (re.search(r"^TASK:\s*(\w+)", user, flags=re.M) or [None, "chunk"])[1]
        track = (re.search(r"^TRACK:\s*(\w+)", user, flags=re.M) or [None, "pinyin"])[1]
        if task == "ideas":
            payload = self._ideas(track, _field(user, "COUNT", 6))
        elif task == "outline":
            payload = self._outline(track, _field(user, "BEATS_REQUIRED", 4))
        else:
            payload = self._chunk(track, _field(user, "LINES_REQUIRED", 10), _field(user, "LINES_DONE", 0))
        text = json.dumps(payload, ensure_ascii=False)
        return LLMResult(text=text, input_tokens=len(user) // 3, output_tokens=len(text) // 3)

    # ----------------------------------------------------------------------------------
    def _ideas(self, track, count):
        zh = [
            ("The Monkey and the Moon's Reflection", "Sun Wukong tries to catch the moon in a well and learns what a reflection is.", "myth", "ancient_tale"),
            ("Nezha and the Dragon King's Son", "A boy with a fire-spear and a river that is not what it seems.", "myth", "storyteller"),
            ("Zhu Bajie's Longest Nap", "The pig who loves food sleeps through a very important night.", "myth", "storyteller"),
            ("Heracles and the Nemean Lion", "The first labour, told in short, strong lines.", "myth", "ancient_tale"),
            ("The World of Tamriel (lore only)", "The land, its provinces and the great events of its history.", "lore_only", "chronicle"),
            ("Chang'e Flies to the Moon", "A quiet tale of a choice and a long silence.", "myth", "ancient_tale"),
        ]
        fr = [
            ("Charlemagne and the Winter Crossing", "The emperor, his army and a very cold pass.", "original", "chronicle"),
            ("Roland's Horn", "The Song of Roland, told in the simplest French.", "adaptation", "faithful"),
            ("Goldilocks and the Three Bears", "A classic told with repetition for beginners.", "adaptation", "fairytale"),
            ("Joan of Arc at Orléans", "A young woman, a siege, and a banner.", "original", "chronicle"),
            ("The Gauls and the Roman Road", "How a village in Gaul met the Romans.", "original", "storyteller"),
            ("Bluebeard's Keys", "A fairy tale about curiosity.", "adaptation", "fairytale"),
        ]
        bank = zh if track == "pinyin" else fr
        out = [dict(title=t, pitch=p, source_mode=m, voice=v) for t, p, m, v in bank]
        return {"ideas": out[:count]}

    def _outline(self, track, n_beats):
        if track == "pinyin":
            title = {"primary": "Shìlì gùshi (demo)", "hanzi": "示例故事（演示）", "english": "A Demo Story"}
            chars = [{"english": "the little monkey", "hanzi": "小猴子", "primary": "Xiǎo hóuzi"}]
        else:
            title = {"primary": "Le petit renard (démo)", "hanzi": "小狐狸（演示）", "english": "The Little Fox (demo)"}
            chars = [{"english": "the little fox", "hanzi": "小狐狸", "primary": "le petit renard"}]
        beats = [{"summary": f"Demo part {i + 1}: the hero goes a little further on the road."} for i in range(n_beats)]
        return {"title": title, "synopsis": "Offline demo story: canned sentences to test the app.", "characters": chars, "beats": beats}

    def _chunk(self, track, n, done):
        lines = []
        for j in range(n):
            i = (done + j) % (len(ZH_BANK) if track == "pinyin" else len(FR_BANK))
            if track == "pinyin":
                hz, en = ZH_BANK[i]
                lines.append({"pinyin": pinyin_from_hanzi(hz), "hanzi": hz, "english": en})
            else:
                fr, hz, en = FR_BANK[i]
                lines.append({"french": fr, "hanzi": hz, "english": en})
        return {"lines": lines}
