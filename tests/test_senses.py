import time

from pythonosc.udp_client import SimpleUDPClient

from muse_body.senses import Senses


def test_reads_params_and_reports_touch():
    s = Senses(port=19001).start()
    try:
        c = SimpleUDPClient("127.0.0.1", 19001)
        c.send_message("/avatar/parameters/VelocityMagnitude", 1.5)
        c.send_message("/avatar/parameters/Grounded", True)
        c.send_message("/avatar/parameters/HeadPat", True)
        c.send_message("/avatar/parameters/HeadPat", True)  # still true: no second event
        deadline = time.time() + 2
        while s.get("HeadPat") is None and time.time() < deadline:
            time.sleep(0.01)
        assert s.speed() == 1.5
        assert s.summary() == "speed 1.5 m/s, on the ground"
        assert s.take_events() == ["HeadPat became true"]
        assert s.take_events() == []
    finally:
        s.close()
