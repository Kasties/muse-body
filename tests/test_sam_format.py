from muse_body.sam_format import parse

LINE = (
    "<0f>1<|box;x1=100;y1=50;x2=300;y2=450;w=1280;h=720;c=0.91|><|mask;data=400,200,!abc|>,"
    "2<|box;x1=900;y1=200;x2=1000;y2=400;w=1280;h=720;c=0.40|><|mask;data=200,100,!def|>"
)


def test_parses_two_records():
    dets = parse(LINE)
    assert [d.obj_id for d in dets] == ["1", "2"]
    a = dets[0]
    assert (a.x1, a.y1, a.x2, a.y2, a.frame_w, a.frame_h) == (100, 50, 300, 450, 1280, 720)
    assert a.conf == 0.91
    assert a.mask == "400,200,!abc"
    assert dets[1].conf == 0.40


def test_fields_by_key_not_position():
    dets = parse("<0f>7<|box;w=640;h=480;y2=40;x2=30;y1=20;x1=10|>")
    assert len(dets) == 1
    d = dets[0]
    assert (d.x1, d.y1, d.x2, d.y2) == (10, 20, 30, 40)
    assert d.conf is None


def test_mask_payload_with_base85_punctuation():
    line = "<0f>1<|box;x1=1;y1=2;x2=3;y2=4;w=8;h=8|><|mask;data=2,2,~a|b<c;d,e|>"
    (d,) = parse(line)
    assert d.mask == "2,2,~a|b<c;d,e"


def test_empty_output():
    assert parse("") == []
    assert parse("<0f>") == []
