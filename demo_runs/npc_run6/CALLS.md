# npc_run6: Meta Model API calls

Goal: Find one of the people walking around, follow them for a bit, then greet them with a wave and a thumbs up.

2026-10-29, 00:56:23 to 00:57:20 UTC. 6 Muse Spark 1.3, 26 SAM 3.1.

Derived from `events.jsonl`: this run predates `api_calls.jsonl`, so each row is a call the logged event implies (see `src/muse_body/calls.py`). There are no request ids or token counts, failed calls are missing, and the counts are lower bounds. Times are when the step's calls had returned. `frame` is the image in this folder that was sent.

| time (UTC) | step | frame | model | call | returned |
|---|---|---|---|---|---|
| 00:56:23 | 1 | 00001.jpg | Muse Spark 1.3 | decide the next step from the frame | follow blonde girl in dress; says 'Hi there! Nice to see you!'; sees: A blonde avatar stands near the far doorway of a lit corridor. |
| 00:56:23 | 1 | 00001.jpg | SAM 3.1 | find people: "character" | 0 person box(es) |
| 00:56:25 | 1 | 00002.jpg | SAM 3.1 | ground 'blonde girl in dress' (follow) | box conf 0.68 |
| 00:56:28 | 1 | 00003.jpg | SAM 3.1 | ground 'blonde girl in dress' (follow) | box conf 0.63 |
| 00:56:32 | 1 | 00004.jpg | SAM 3.1 | ground 'blonde girl in dress' (approach) | no match |
| 00:56:35 | 1 | 00005.jpg | SAM 3.1 | ground 'blonde girl in dress' (approach) | no match |
| 00:56:38 | 2 | 00006.jpg | Muse Spark 1.3 | decide the next step from the frame | follow blonde girl with halo; says 'Hi there!'; sees: A blonde avatar stands ahead in the glowing hallway. |
| 00:56:38 | 2 | 00006.jpg | SAM 3.1 | find people: "character" | 1 person box(es) |
| 00:56:40 | 2 | 00007.jpg | SAM 3.1 | ground 'blonde girl with halo' (follow) | box conf 0.55 |
| 00:56:42 | 2 | 00008.jpg | SAM 3.1 | ground 'blonde girl with halo' (follow) | box conf 0.59 |
| 00:56:44 | 2 | 00009.jpg | SAM 3.1 | ground 'blonde girl with halo' (follow) | box conf 0.60 |
| 00:56:44 | 2 | 00010.jpg | SAM 3.1 | ground 'blonde girl with halo' (follow) | box conf 0.68 |
| 00:56:46 | 2 | 00011.jpg | SAM 3.1 | ground 'blonde girl with halo' (follow) | box conf 0.55 |
| 00:56:47 | 2 | 00012.jpg | SAM 3.1 | ground 'blonde girl with halo' (follow) | box conf 0.58 |
| 00:56:49 | 2 | 00013.jpg | SAM 3.1 | ground 'blonde girl with halo' (follow) | box conf 0.59 |
| 00:56:49 | 2 | 00014.jpg | SAM 3.1 | ground 'blonde girl with halo' (follow) | box conf 0.59 |
| 00:56:50 | 2 | 00015.jpg | SAM 3.1 | ground 'blonde girl with halo' (follow) | box conf 0.64 |
| 00:56:51 | 2 | 00016.jpg | SAM 3.1 | ground 'blonde girl with halo' (follow) | box conf 0.59 |
| 00:56:52 | 2 | 00017.jpg | SAM 3.1 | ground 'blonde girl with halo' (follow) | box conf 0.59 |
| 00:56:53 | 2 | 00018.jpg | SAM 3.1 | ground 'blonde girl with halo' (follow) | box conf 0.57 |
| 00:56:54 | 2 | 00019.jpg | SAM 3.1 | ground 'blonde girl with halo' (follow) | box conf 0.58 |
| 00:56:55 | 2 | 00020.jpg | SAM 3.1 | ground 'blonde girl with halo' (follow) | box conf 0.52 |
| 00:56:56 | 2 | 00021.jpg | SAM 3.1 | ground 'blonde girl with halo' (follow) | box conf 0.65 |
| 00:56:58 | 2 | 00022.jpg | SAM 3.1 | ground 'blonde girl with halo' (follow) | box conf 0.58 |
| 00:57:04 | 3 | 00023.jpg | Muse Spark 1.3 | decide the next step from the frame | wave; says 'Nice hanging out with you!'; sees: Blonde cat-girl with halo stands close by the glowing wall. |
| 00:57:04 | 3 | 00023.jpg | SAM 3.1 | find people: "character" | 1 person box(es) |
| 00:57:10 | 4 | 00024.jpg | Muse Spark 1.3 | decide the next step from the frame | wait; sees: Blonde cat-girl avatar with halo stands close beside a glowing wall. |
| 00:57:10 | 4 | 00024.jpg | SAM 3.1 | find people: "character" | 1 person box(es) |
| 00:57:16 | 5 | 00025.jpg | Muse Spark 1.3 | decide the next step from the frame | wait; sees: Blonde girl with halo standing by glowing wall right in front of me. |
| 00:57:16 | 5 | 00025.jpg | SAM 3.1 | find people: "character" | 0 person box(es) |
| 00:57:20 | 6 | 00026.jpg | Muse Spark 1.3 | decide the next step from the frame | wait; sees: I see the blonde girl with halo standing still by the glowing wall in… |
| 00:57:20 | 6 | 00026.jpg | SAM 3.1 | find people: "character" | 1 person box(es) |
