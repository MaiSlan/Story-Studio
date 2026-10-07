from app.pinyin_tools import check_pinyin, pinyin_from_hanzi, traditional_diffs


def codes(h, p, names=None):
    return [(i.level, i.code) for i in check_pinyin(h, p, names)]


def test_correct_line_passes():
    assert codes("孙悟空拿起金箍棒。", "Sūn Wùkōng náqǐ jīngūbàng.") == []


def test_missing_syllable_is_an_error():
    assert ("error", "syllable_mismatch") in codes("孙悟空拿起金箍棒。", "Sūn Wùkōng náqǐ jīngū.")


def test_extra_syllable_is_an_error():
    assert ("error", "extra_pinyin") in codes("你好。", "Nǐ hǎo ma.")


def test_tone_numbers_rejected():
    assert ("error", "tone_numbers") in codes("你好", "Ni3 hao3")


def test_wrong_tone_is_a_warning():
    assert ("warn", "tone") in codes("我喜欢苹果。", "Wǒ xǐhuān píngguō.")  # 苹 is 2nd tone, 果 is 3rd


def test_textbook_sandhi_is_accepted():
    assert codes("他不去。我一个人。", "Tā bú qù. Wǒ yí gè rén.") == []
    assert codes("你好", "Ní hǎo") == []  # third-tone sandhi written as pronounced is tolerated


def test_neutral_tone_and_erhua_and_particle_di():
    assert codes("我的朋友很好。", "Wǒ de péngyou hěn hǎo.") == []
    assert codes("她喝了一会儿茶。", "Tā hēle yíhuìr chá.") == []
    assert codes("水慢慢地不动了。", "Shuǐ mànmàn de bú dòng le.") == []


def test_name_spelling_is_enforced():
    names = [("孙悟空", "Sūn Wùkōng")]
    assert codes("孙悟空走了。", "Sūn Wùkōng zǒu le.", names) == []
    assert ("warn", "name_spelling") in codes("孙悟空走了。", "Sūn Wùgōng zǒu le.", names)


def test_rebuild_pinyin_matches_hanzi():
    hanzi = "孙悟空说：“你好！”"
    rebuilt = pinyin_from_hanzi(hanzi, [("孙悟空", "Sūn Wùkōng")])
    assert rebuilt.startswith("Sūn Wùkōng")
    assert [i for i in check_pinyin(hanzi, rebuilt, [("孙悟空", "Sūn Wùkōng")]) if i.level == "error"] == []


def test_rebuild_applies_bu_and_yi_sandhi():
    assert "bú qù" in pinyin_from_hanzi("他不去")
    assert "yì zhī" in pinyin_from_hanzi("一只猫").lower()


def test_traditional_characters_detected():
    assert traditional_diffs("說話") == [("說", "说"), ("話", "话")]
    assert traditional_diffs("说话") == []
