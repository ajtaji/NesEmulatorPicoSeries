"""Replay three NTSC games in the N64 emulator using locally supplied NES ROMs."""
import argparse
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import re
import wave

from PIL import Image

from build import build
from verify import run_headless


@dataclass(frozen=True)
class Replay:
    rom_hash: str
    controls: tuple
    first: int
    last: int
    stop: int
    state_hash: str
    rgb_hash: str
    pcm_hash: str


# The reference is the port before the gameplay optimizations. Hash the
# guest-frame checkpoints separately from the modeled N64 Count register.
GAMES = {
    "Mario": Replay(
        "f61548fdf1670cffefcc4f0b7bdcdd9eaba0c226e3b74f8666071496988248de",
        ((100,106,8), (175,222,128), (222,248,129), (248,274,128),
         (274,300,129), (300,319,128), (319,342,129), (342,400,128)),
        240, 360, 360,
        "782877377e5cc0f687fd0abe4880106a2a0e3fdef9ae04252d3b1f9187ea6c68",
        "e009aaf88d1daca411b38c819ab674e58cd391d675a1b1e34b18912a2d9bde04",
        "52c3b28ce1497d8486a73bc1fac9bef4f8f7a22b065a4d92f0837825f3470be7"),
    "Zelda": Replay(
        "8f72dc2e98572eb4ba7c3a902bca5f69c448fc4391837e5f8f0d4556280440ac",
        ((100,104,8), (150,154,8), (210,214,1), (230,234,4), (245,249,4),
         (260,264,4), (280,284,8), (330,334,8), (395,425,16), (460,490,128), (500,510,1)),
        480, 540, 550,
        "87824ef57f5c7d6af8935fc2cdd6d36fb6376017781824d5928945a544f45ec4",
        "84a8d0e1158c9289529e483d645b071bd63564b4b1a38554581ead40ac5d0e1d",
        "64eef0fec30d68581ce674b5f0745133bd9d450783264a285605f47e1b8cd5f4"),
    "MegaMan2": Replay(
        "27b5a635df33ed57ed339dfc7fd62fc603b39c1d1603adb5cdc3562a0b0d555b",
        ((100,104,8), (150,154,8), (225,229,8), (300,304,8), (410,414,128),
         (420,424,8), (1100,1118,128), (1118,1134,129), (1134,1140,130),
         (1140,1155,128), (1160,1166,2), (1174,1188,64), (1200,1214,128),
         (1214,1230,129), (1230,1236,130), (1236,1260,128)),
        1080, 1260, 1260,
        "566af03c002638c8a6df4987b69affadbb84819db18116275f3292ed825a1a1f",
        "a4b96b481006c04d443cbfe85a18368b35f429b512843c113a1eaf67d707cc84",
        "01a25809c4699e274843797ef1af97ef5e0eb51ecd7c725475f7e56925403104"),
}


# Native 20 kHz keeps the same guest PCs and cycle counts. The reduced
# sample cadence and its rate-adjusted DC filter have their own references.
AUDIO_20K = {
    "Mario": (
        "4e762187ef6198fd5a17f40be5b2f3d17c2e45050dea1a1b688203b3897d2a8d",
        "880f246fb796fdf643b7ffd85b1d764492ebfe61dbb09f41249d6f7d80cc7604"),
    "Zelda": (
        "7579260d126b0be086cf094fbb770b5defbdd79360a579bf665f89e73d1969a1",
        "b26e1a6b880ca821884a45bcbe3bbb337a0e5e97ea6f13f87a45412691c3a51f"),
    "MegaMan2": (
        "73f91d641deedec1ce56d921827f6163f1adef6f1b8df451f2660c8452c51cfd",
        "46d12970b9fc7fa7c48eb1c69948cbf7ee1a65a0275bbf14052a8a71255a4d39"),
}

def wood_man_controls(stop):
    return GAMES["MegaMan2"].controls + tuple(
        (frame + first, frame + end, buttons)
        for frame in range(1260, stop, 120)
        for first, end, buttons in (
            (0, 20, 128), (20, 35, 129), (35, 42, 130), (42, 66, 128),
            (70, 78, 2), (80, 93, 64), (96, 120, 128),
        )
    )


WOOD_MAN_EXTENDED = replace(
    GAMES["MegaMan2"],
    controls=wood_man_controls(1860),
    last=1860,
    stop=1860,
    state_hash="e244535315c4c59e2939d22b59c9277163764bc97d0ed9e0dce5f26a467de4b2",
    rgb_hash="e80b4eb884e772a999933301190161f78abcce7cb260ef3b429952b637e218da",
    pcm_hash="ac0c943192ef77910c9be2d83d854f14e8a22d20fba85d9a07f6a6e9c633daf9",
)


WOOD_MAN_ENDURANCE = replace(
    WOOD_MAN_EXTENDED, controls=wood_man_controls(3060), last=3060, stop=3060,
    state_hash="c3ed5478a22195f730720d11adb587b4c6680213c58e22719701750cbcea4366",
    rgb_hash="5ddbbb816533a4908d42d8ccd2832ac4b6dfd9b740c63e14e1d6680f9412385d",
    pcm_hash="fa56bfecebf730434cfe778453ba3abff5f4d82ca67d58dc7216250077674854",
)


# Keep the short replay inputs through frame 360, then continue playing
# World 1-1 with alternating runs, jumps and pauses.
MARIO_ENDURANCE = replace(
    GAMES["Mario"],
    controls=GAMES["Mario"].controls[:-1] + (
        (342, 360, 128), (360, 399, 128), (399, 427, 129),
        (436, 468, 128), (468, 490, 129), (515, 550, 128), (550, 578, 129),
        (610, 632, 128), (632, 660, 129), (692, 718, 128), (718, 747, 129),
        (798, 824, 128), (824, 849, 129), (877, 901, 128), (901, 928, 129),
        (965, 986, 128), (986, 1016, 129), (1060, 1086, 128), (1086, 1120, 129),
    ),
    first=360, last=1140, stop=1140,
    state_hash="8cb0730ed8dd44a2139b4d4d478def55c672c5131cacb27e14128be4abd086c0",
    rgb_hash="b5d3e2b67298b35e7e818b04839802481cafb029e307210b4be41d5b0cd6addc",
    pcm_hash="5d037f7d2893fabb1e5b01b278f3f8f3f4b44b2815a8d6a204fee783d3a97b39",
)
ZELDA_ENDURANCE = replace(
    GAMES["Zelda"],
    # Enter the cave, approach the old man, collect the sword and leave.
    controls=GAMES["Zelda"].controls + (
        (550, 622, 64), (622, 780, 16), (1038, 1044, 128), (1044, 1120, 16),
        (1160, 1280, 32), (1285, 1325, 128), (1330, 1410, 16),
        (1415, 1423, 1), (1423, 1440, 128),
    ),
    first=540, last=1440, stop=1440,
    state_hash="7bdc0284183e6773e22aaa2372afb091def3328bea39b93000bc70caee0f000a",
    rgb_hash="ba324f4c7e5ef7b79b43c57f7d2d707222dda022884d5030eeb0061c898c424e",
    pcm_hash="1affa8141096c8c5f441fc2b02b53046d04fc1e3cf597a4763580e8f72491c0d",
)
ENDURANCE = {"Mario": MARIO_ENDURANCE, "Zelda": ZELDA_ENDURANCE, "MegaMan2": WOOD_MAN_ENDURANCE}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify(args):
    extended = getattr(args, "extended", False)
    game = WOOD_MAN_EXTENDED if extended else GAMES[args.game]
    if getattr(args, "endurance", False):
        extended = True
        game = ENDURANCE[args.game]
    if digest(args.rom.read_bytes()) != game.rom_hash:
        raise ValueError(f"this replay requires the {args.game} ROM with SHA-256 {game.rom_hash}")
    state_hash, pcm_hash = (AUDIO_20K[args.game] if args.audio_rate == 20000 and not extended
                            else (game.state_hash, game.pcm_hash))
    work = args.results.resolve()
    work.mkdir(parents=True, exist_ok=True)
    args.out = work / "replay.z64"
    args.check_frame = game.stop
    build(args, controller_trace=game.controls)
    report, frame, pcm = [work / name for name in ("report.txt", "frame.png", "sound.wav")]
    run_headless(args.sdk, args.emulator, args.out, "--ram", "4", "--frames", str(game.stop * 3),
                 "--test", report, "--png", frame, "--wav", pcm)
    log = report.read_text()
    if f"NES CHECKPOINT {game.stop}" not in log or "NES STOP" in log or "FIRST code " in log:
        raise ValueError(f"cartridge did not finish cleanly. See {report}")
    states = re.findall(r"^NES FRAME (\d+) CPU (\d+) PCM (\d+) PC (\d+) COUNT (\d+)", log, re.M)
    if digest("\n".join(" ".join(state[:4]) for state in states).encode()) != state_hash:
        raise ValueError("guest CPU cycles, sample clock or PC changed")
    with Image.open(frame) as image:
        if image.size != (320, 240) or digest(image.convert("RGB").tobytes()) != game.rgb_hash:
            raise ValueError("gameplay framebuffer changed")
    with wave.open(str(pcm)) as sound:
        if (abs(sound.getframerate() - args.audio_rate) > 50
                or sound.getnchannels() != 2 or sound.getsampwidth() != 2
                or digest(sound.readframes(sound.getnframes())) != pcm_hash):
            raise ValueError("captured stereo stream changed")
    clocks = {int(row[0]): int(row[-1]) for row in states}
    gaps = {int(f): int(n) for n, f in re.findall(r"^NES AI QUEUED \d+ UNDERRUNS (\d+) FRAME (\d+)", log, re.M)}
    coalesced = {int(f): int(n) for n, f in re.findall(r"^NES AI READY ON EMPTY \d+ LAST \d+ COALESCED (\d+) FRAME (\d+)", log, re.M)}

    def interval(first, last):
        ticks = (clocks[last] - clocks[first]) & 0xffffffff
        rate = (last - first) * 46_875_000 / ticks
        return (f"guest frames {first} to {last}: {rate:.3f} fps, {gaps[last] - gaps[first]} audio underruns, "
                f"{coalesced[last] - coalesced[first]} coalesced presentations")

    summary = f"{args.game} {interval(game.first, game.last)}; reference state, picture and PCM match."
    metrics = [summary]
    if extended:
        if args.game == "MegaMan2":
            metrics.append(interval(1260, game.last))
        metrics.extend(interval(frame, frame + 60) for frame in range(game.first, game.last, 60))
    (work / "metrics.txt").write_text("\n".join(metrics) + "\n")
    print(summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", choices=GAMES)
    parser.add_argument("--audio-rate", type=int, choices=(20000, 48000),
                        help="default 48000, or 20000 for the extended replay")
    length = parser.add_mutually_exclusive_group()
    length.add_argument("--endurance", action="store_true", help="play a longer active gameplay route at 20 kHz")
    length.add_argument("--extended", action="store_true", help="continue MegaMan2 through Wood Man at 20 kHz")
    for option in ("sdk", "emulator", "rom", "results"):
        parser.add_argument("--" + option, type=Path, required=True)
    args = parser.parse_args()
    if args.extended and args.game != "MegaMan2":
        parser.error("--extended is available for MegaMan2")
    if (args.extended or args.endurance) and args.audio_rate == 48000:
        parser.error("long replays require 20 kHz")
    if args.audio_rate is None:
        args.audio_rate = 20000 if args.extended or args.endurance else 48000
    verify(args)
