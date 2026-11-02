from muse_body.agent import SYSTEM, Errands, Memory
from muse_body.body import MOODS, Body


def test_prompt_offers_the_moods_the_body_knows():
    line = next(x for x in SYSTEM.splitlines() if x.strip().startswith('"mood"'))
    assert [m for m in MOODS if f'"{m}"' in line] == MOODS


def test_thinking_and_mood_go_out_over_osc(capsys):
    body = Body(dry_run=True)
    body.thinking(True)
    body.mood("curious")
    body.mood("grumpy")  # not a mood the avatar has: nothing sent
    assert capsys.readouterr().out.splitlines() == [
        "[osc] /avatar/parameters/Thinking True", "[osc] /chatbox/typing True",
        "[osc] /avatar/parameters/Mood 2"]


def ask(**kw):
    d = {"heard": None, "new_errand": None, "requester": None, "errand_done": False}
    d.update(kw)
    return d


def test_bubble_starts_one_errand_while_it_stays_up():
    e = Errands()
    fresh, errand = e.read(ask(heard="Can you bring me the menu?", new_errand="bring the menu",
                               requester="Kasties, red hoodie"))
    assert fresh and errand == {"task": "bring the menu", "for": "Kasties, red hoodie",
                                "heard": "Can you bring me the menu?"}
    # The same bubble in the next frames (case and spacing may differ): no new errand, no reply.
    assert e.read(ask(heard="can you bring me  the menu?", new_errand="bring the menu")) == (False, None)
    assert e.current["task"] == "bring the menu"
    assert "who wrote 'Can you bring me the menu?'" in e.describe()


def test_done_clears_and_old_words_do_not_restart():
    e = Errands()
    e.read(ask(heard="grab me a cup", new_errand="bring a cup"))
    e.read(ask(heard="grab me a cup", errand_done=True))
    assert e.current is None and e.describe() is None
    assert e.read(ask(heard="grab me a cup", new_errand="bring a cup")) == (False, None)
    fresh, errand = e.read(ask(heard="now the menu please", new_errand="bring the menu"))
    assert fresh and errand["task"] == "bring the menu"


def test_give_keeps_errand_until_handed_over():
    # Offline 11-02: Muse Spark set errand_done in the decision that starts the give.
    e = Errands()
    e.read(ask(heard="bring me the menu", new_errand="bring the menu"))
    e.read(ask(intent="give", errand_done=True))
    assert e.current["task"] == "bring the menu"


def test_chat_without_request_is_fresh_once():
    e = Errands()
    assert e.read(ask(heard="hi!")) == (True, None)
    assert e.read(ask(heard="hi!")) == (False, None)
    assert e.current is None


def test_inferred_errand_without_words_once():
    e = Errands()
    assert e.read(ask(new_errand="bring the menu"))[1] is not None
    e.done()
    assert e.read(ask(new_errand="bring the menu")) == (False, None)


def test_prompt_lists_errand():
    p = Memory().prompt("help people", body="standing still", errand="bring the menu (asked by Kasties)")
    assert p.index("Errand: bring the menu") < p.index("Body:") < p.index("Recent:")
    assert "Errand" not in Memory().prompt("help people")
