"""answer_files.scan: segment A of docs/handoff-file-preview.md §3.

Temporary folders and made-up file names only.  Table-driven: every writing form in §3.2
has a case, plus the contract with the three clients' localPath rules, idempotence, code
untouched, and the old web's index numbering.
"""
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import answer_files


def make(root: Path, name: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture", encoding="utf-8")
    return path


class Env:
    def __init__(self, root: Path, home: Path):
        self.root = root
        self.home = home
        self.posix = root.as_posix()
        self.win = str(root)
        self.bases = [str(root)]

    def path(self, name: str) -> str:
        return str(self.root / name)

    def posix_path(self, name: str) -> str:
        return (self.root / name).as_posix()

    def scan(self, text, **options):
        options.setdefault("bases", self.bases)
        return answer_files.scan(text, **options)


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("chart.png", "b.R", "src/app.ts", "out/report.md",
                 "sub/.hidden/f.md", "a_b.md", "dir with space/x.txt",
                 "b%20c.png"):
        make(tmp_path, name)
    make(tmp_path, "报告 图 (1).png")
    make(tmp_path, "100%.txt")
    make(tmp_path, "space name.txt")
    (tmp_path / "folder").mkdir()
    home = tmp_path / "home"
    make(home, "docs/home.txt")
    monkeypatch.setattr(answer_files, "_home", lambda: str(home))
    return Env(tmp_path, home)


# The three client rules, copied so a changed client rule fails here (handoff §9).
def android_local(destination):
    path = unquote(destination.replace("+", "%2B"))
    if not re.match(r"^[A-Za-z]:[\\/]", path):
        return None
    return re.sub(r":\d+(?:-\d+)?$", "", path)


def ios_local(destination):
    path = unquote(destination)
    if not re.match(r"^[A-Za-z]:[\\/]", path):
        return None
    return re.sub(r":\d+(?:-\d+)?$", "", path)


def web_local(destination):
    path = unquote(destination)
    return bool(re.match(r"^[A-Za-z]:[\\/]", path))


def normalized(path: str) -> str:
    return unquote(path).replace("\\", "/").casefold()


MARKDOWN_FORMS = [
    "drive_backslash", "drive_forward", "leading_slash", "leading_backslash",
    "file_url_triple", "file_url_localhost", "file_url_drive_host", "file_url_one_slash",
    "long_path", "wsl_mount", "home", "home_backslash", "relative", "relative_dot",
    "relative_line", "chinese_image", "angle_spaces", "image_nested_alt",
    "percent_space", "percent_escape",
    "percent_broken", "backslash_escape", "title", "colon_line", "colon_range",
    "hash_line", "hash_column", "hash_range", "folder", "missing_absolute",
]


def markdown_form(env: Env, name: str) -> dict:
    p = env.posix
    file = env.path("chart.png")
    out = env.posix_path("chart.png")
    if name == "drive_backslash":
        return {"text": f"[打开]({file})", "text_out": f"[打开](<{out}>)",
                "path": file, "via": "link", "index": 0}
    if name == "drive_forward":
        return {"text": f"[打开]({p}/chart.png)", "text_out": f"[打开](<{out}>)",
                "path": file, "via": "link", "index": 0}
    if name == "leading_slash":
        return {"text": f"[打开](/{p}/chart.png)", "text_out": f"[打开](<{out}>)",
                "path": file, "via": "link", "index": 0}
    if name == "leading_backslash":
        return {"text": f"[打开](\\{env.win}/chart.png)", "text_out": f"[打开](<{out}>)",
                "path": file, "via": "link", "index": 0}
    if name == "file_url_triple":
        return {"text": f"[打开](file:///{p}/chart.png)", "text_out": f"[打开](<{out}>)",
                "path": file, "via": "link", "index": 0}
    if name == "file_url_localhost":
        return {"text": f"[打开](file://localhost/{p}/chart.png)",
                "text_out": f"[打开](<{out}>)", "path": file, "via": "link", "index": 0}
    if name == "file_url_drive_host":
        return {"text": f"[打开](file://{p}/chart.png)", "text_out": f"[打开](<{out}>)",
                "path": file, "via": "link", "index": 0}
    if name == "file_url_one_slash":
        return {"text": f"[打开](file:/{p}/chart.png)", "text_out": f"[打开](<{out}>)",
                "path": file, "via": "link", "index": 0}
    if name == "long_path":
        return {"text": "[打开](\\\\?\\" + env.path("chart.png") + ")",
                "text_out": f"[打开](<{out}>)", "path": file, "via": "link", "index": 0}
    if name == "wsl_mount":
        mount = "/mnt/" + p[0].lower() + p[2:]
        return {"text": f"[打开]({mount}/chart.png)", "text_out": f"[打开](<{out}>)",
                "path": file, "via": "link", "index": 0}
    if name == "home":
        return {"text": "[打开](~/docs/home.txt)",
                "text_out": f"[打开](<{env.home.as_posix()}/docs/home.txt>)",
                "path": str(env.home / "docs/home.txt"), "via": "link", "index": 0}
    if name == "home_backslash":
        return {"text": "[打开](~\\docs\\home.txt)",
                "text_out": f"[打开](<{env.home.as_posix()}/docs/home.txt>)",
                "path": str(env.home / "docs/home.txt"), "via": "link", "index": 0}
    if name == "relative":
        return {"text": "[打开](src/app.ts)", "text_out": f"[打开](<{p}/src/app.ts>)",
                "path": env.path("src/app.ts"), "via": "link", "index": 0}
    if name == "relative_dot":
        return {"text": "[打开](./src/app.ts)", "text_out": f"[打开](<{p}/src/app.ts>)",
                "path": env.path("src/app.ts"), "via": "link", "index": 0}
    if name == "relative_line":
        return {"text": "[打开](src/app.ts:42)", "text_out": f"[打开](<{p}/src/app.ts:42>)",
                "path": env.path("src/app.ts"), "via": "link", "index": 0, "line": 42}
    if name == "chinese_image":
        source = env.path("报告 图 (1).png")
        out = env.posix_path("报告 图 (1).png")
        return {"text": f'![图](<{source}> "标题")', "text_out": f'![图](<{out}> "标题")',
                "path": source, "via": "image", "index": 0}
    if name == "image_nested_alt":
        return {"text": f"![图 [1]]({file})", "text_out": f"![图 [1]](<{out}>)",
                "path": file, "via": "image", "index": 0}
    if name == "angle_spaces":
        source = env.path("space name.txt")
        out = env.posix_path("space name.txt")
        return {"text": f"[打开](<{source}>)", "text_out": f"[打开](<{out}>)",
                "path": source, "via": "link", "index": 0}
    if name == "percent_space":
        return {"text": "[打开](space%20name.txt)",
                "text_out": f"[打开](<{p}/space name.txt>)",
                "path": env.path("space name.txt"), "via": "link", "index": 0}
    if name == "percent_escape":
        return {"text": "[打开](100%25.txt)", "text_out": f"[打开](<{p}/100%25.txt>)",
                "path": env.path("100%.txt"), "via": "link", "index": 0}
    if name == "percent_broken":
        return {"text": "[打开](100%.txt)", "text_out": f"[打开](<{p}/100%25.txt>)",
                "path": env.path("100%.txt"), "via": "link", "index": 0}
    if name == "backslash_escape":
        source = env.path("sub/.hidden/f.md")
        out = env.posix_path("sub/.hidden/f.md")
        return {"text": f"[打开]({source})", "text_out": f"[打开](<{out}>)",
                "path": source, "via": "link", "index": 0}
    if name == "title":
        return {"text": f'[打开]({file} "标题")', "text_out": f'[打开](<{out}> "标题")',
                "path": file, "via": "link", "index": 0}
    if name == "colon_line":
        return {"text": f"[打开]({p}/src/app.ts:12:5)",
                "text_out": f"[打开](<{p}/src/app.ts:12>)",
                "path": env.path("src/app.ts"), "via": "link", "index": 0, "line": 12}
    if name == "colon_range":
        return {"text": f"[打开]({p}/src/app.ts:12-20)",
                "text_out": f"[打开](<{p}/src/app.ts:12>)",
                "path": env.path("src/app.ts"), "via": "link", "index": 0, "line": 12}
    if name == "hash_line":
        return {"text": f"[打开]({p}/out/report.md#L12)",
                "text_out": f"[打开](<{p}/out/report.md:12>)",
                "path": env.path("out/report.md"), "via": "link", "index": 0, "line": 12}
    if name == "hash_column":
        return {"text": f"[打开]({p}/out/report.md#L12C5)",
                "text_out": f"[打开](<{p}/out/report.md:12>)",
                "path": env.path("out/report.md"), "via": "link", "index": 0, "line": 12}
    if name == "hash_range":
        return {"text": f"[打开]({p}/out/report.md#L12-L20)",
                "text_out": f"[打开](<{p}/out/report.md:12>)",
                "path": env.path("out/report.md"), "via": "link", "index": 0, "line": 12}
    if name == "folder":
        return {"text": f"[打开]({p}/folder)", "text_out": f"[打开](<{p}/folder>)",
                "path": env.path("folder"), "via": "link", "index": 0,
                "exists": True, "is_dir": True}
    if name == "missing_absolute":
        return {"text": f"[打开]({p}/missing.png)",
                "text_out": f"[打开](<{p}/missing.png>)",
                "path": env.path("missing.png"), "via": "link", "index": 0, "exists": False}
    raise AssertionError(name)


@pytest.mark.parametrize("form", MARKDOWN_FORMS)
def test_markdown_writing_forms(env, form):
    spec = markdown_form(env, form)
    result = env.scan(spec["text"])
    assert result.text == spec["text_out"]
    assert len(result.files) == 1
    row = result.files[0]
    assert row["path"] == spec["path"]
    assert row["line"] == spec.get("line")
    assert row["via"] == [spec["via"]]
    assert row["index"] == spec["index"]
    assert row["exists"] is spec.get("exists", True)
    assert row["is_dir"] is spec.get("is_dir", False)
    assert result.notes == []


def test_relative_parent_folder(env):
    work = env.root / "work"
    work.mkdir()
    make(env.root / "shared", "x.txt")
    result = env.scan("[打开](../shared/x.txt)", bases=[str(work)])
    assert result.files[0]["path"] == str(env.root / "shared" / "x.txt")
    assert result.text == f"[打开](<{env.posix}/shared/x.txt>)"


def test_reference_style_rewrites_definition(env):
    text = f'[图][pic]\n\n[pic]: <{env.win}/chart.png> "标题"\n'
    result = env.scan(text)
    assert result.text == f'[图][pic]\n\n[pic]: <{env.posix}/chart.png> "标题"\n'
    assert result.files[0]["path"] == env.path("chart.png")
    assert result.files[0]["index"] == 0


def test_shortcut_reference_and_line_number(env):
    text = "[报告]\n\n[报告]: out/report.md:12\n"
    result = env.scan(text)
    assert result.text == f"[报告]\n\n[报告]: <{env.posix}/out/report.md:12>\n"
    assert result.files[0]["path"] == env.path("out/report.md")
    assert result.files[0]["line"] == 12


def test_relative_hash_line(env):
    result = env.scan("[报告](out/report.md#L12)")
    assert result.text == f"[报告](<{env.posix}/out/report.md:12>)"
    assert result.files[0]["path"] == env.path("out/report.md")
    assert result.files[0]["line"] == 12


def test_filename_with_line_number_is_not_a_url_scheme(env):
    result = env.scan("[脚本](remote.py:905)")
    assert result.files == []
    assert result.notes == [{"href": "remote.py:905", "reason": "not_found"}]


def test_hash_is_kept_when_the_full_name_exists(env):
    make(env.root, "out/report.md#L12")
    result = env.scan(f"[报告]({env.posix}/out/report.md#L12)")
    assert result.files[0]["path"] == env.path("out/report.md#L12")
    assert result.files[0]["line"] is None
    assert result.files[0]["exists"] is True


def test_unicode_nfc(env):
    make(env.root, "caf\u00e9.txt")
    result = env.scan("[cafe](cafe\u0301.txt)")
    assert result.files[0]["path"] == env.path("caf\u00e9.txt")
    assert result.text == f"[cafe](<{env.posix}/caf\u00e9.txt>)"


def test_reference_network_definition(env):
    text = "[x][r]\n\n[r]: <\\\\server\\share\\a.png>\n"
    result = env.scan(text)
    assert result.text == text
    assert result.files == []
    assert result.notes == [{"href": r"\\server\share\a.png", "reason": "not_local"}]


def test_link_inside_list_and_blockquote(env):
    result = env.scan(f"- [a]({env.posix}/chart.png)\n> [b]({env.posix}/b.R)\n")
    assert [row["path"] for row in result.files] == [env.path("chart.png"), env.path("b.R")]
    assert result.files[0]["indexes"] == [0]
    assert result.files[1]["indexes"] == [1]


def test_unused_reference_definition_is_left_alone(env):
    text = "[unused]: out/report.md\n"
    result = env.scan(text)
    assert result.text == text
    assert result.files == [] and result.notes == []


def test_reference_link_used_twice_gets_two_indexes(env):
    text = f"[a][r] [b][r]\n\n[r]: <{env.posix}/chart.png>\n"
    result = env.scan(text)
    assert result.files[0]["indexes"] == [0, 1]


def test_same_file_linked_twice_keeps_both_indexes(env):
    chart = env.posix_path("chart.png")
    desk = env.posix_path("b.R")
    result = env.scan(f"[a]({chart}) [b]({desk}) [c]({chart})")
    rows = {row["path"]: row for row in result.files}
    assert rows[env.path("chart.png")]["indexes"] == [0, 2]
    assert rows[env.path("b.R")]["indexes"] == [1]
    assert [row["index"] for row in result.files] == [0, 1]


def test_missing_and_folder_keep_their_old_web_numbers(env):
    result = env.scan(f"[m]({env.posix}/nope.png) [f]({env.posix}/folder) "
                      f"[real]({env.posix}/chart.png)")
    assert [row["index"] for row in result.files] == [0, 1, 2]
    assert result.files[0]["exists"] is False
    assert result.files[1]["is_dir"] is True
    assert result.files[2]["path"] == env.path("chart.png")


def test_non_markdown_sources_start_at_1000(env):
    text = (f'<img src="{env.path("chart.png")}"> `{env.path("b.R")}` '
            f'{env.path("src/app.ts")}')
    result = env.scan(text, presented=[env.path("out/report.md")])
    assert [row["index"] for row in result.files] == [1000, 1001, 1002, 1003]
    assert [row["via"] for row in result.files] == [
        ["image"], ["code"], ["path"], ["presented"]]
    assert result.files[1]["texts"] == [env.path("b.R")]
    assert result.files[2]["texts"] == [env.path("src/app.ts")]


def test_html_is_recognized_but_never_rewritten(env):
    text = (f'<img src="{env.win}/chart.png">\n'
            f'<a href="{env.posix}/b.R">打开</a>\n')
    result = env.scan(text)
    assert result.text == text
    assert [row["via"] for row in result.files] == [["image"], ["link"]]
    assert [row["index"] for row in result.files] == [1000, 1001]


def test_html_relative_path_resolves(env):
    text = '<a href="src/app.ts">打开</a>'
    result = env.scan(text)
    assert result.text == text
    assert result.files[0]["path"] == env.path("src/app.ts")


def test_html_attribute_that_looks_like_markdown_is_not_a_link(env):
    text = f'<div title="[a]({env.posix}/chart.png)">x</div>'
    result = env.scan(text)
    assert result.text == text
    assert result.files == [] and result.notes == []


def test_html_script_schemes_are_not_files(env):
    for text in ('<img src="javascript:alert(1)">',
                 '<a href="data:text/html,x">x</a>',
                 '<img src="https://example.com/a.png">'):
        result = env.scan(text)
        assert result.files == [] and result.notes == []
        assert result.text == text


def test_codex_citation(env):
    text = f':codex-file-citation{{path="{env.win}/src/app.ts" purpose="output"}}'
    result = env.scan(text)
    assert result.text == text
    assert result.files[0]["path"] == env.path("src/app.ts")
    assert result.files[0]["via"] == ["citation"]
    assert result.files[0]["index"] == 1000
    assert "texts" not in result.files[0]


def test_presented_files(env):
    result = env.scan("答案", presented=[env.path("chart.png")])
    assert result.text == "答案"
    assert result.files[0]["path"] == env.path("chart.png")
    assert result.files[0]["via"] == ["presented"]
    assert result.files[0]["index"] == 1000
    assert "targets" not in result.files[0]  # nothing in the text was rewritten for it


def test_rewritten_links_record_where_they_now_point(env):
    # A note about such a file must name the new address: the phones pair notes with links by it (dev.57).
    result = env.scan("[文件夹](folder) 和 [代码](src/app.ts:12) 和 [再一次](src/app.ts)")
    folder, code = result.files
    assert folder["targets"] == [env.posix_path("folder")] and folder["hrefs"] == ["folder"]
    assert code["targets"] == [env.posix_path("src/app.ts") + ":12", env.posix_path("src/app.ts")]
    for target in folder["targets"] + code["targets"]:
        assert f"](<{target}>)" in result.text
    assert answer_files.markdown_address(env.path("100%.txt")) == "<" + env.posix_path("100%25.txt") + ">"


def test_presented_network_file_is_skipped_without_stat(env):
    calls = []

    def guard(path):
        calls.append(path)
        raise AssertionError(path)

    result = env.scan("答案", presented=[r"\\server\share\x.png"], stat=guard)
    assert result.files == []
    assert calls == []


def test_inline_code_single_path_only_goes_to_texts(env):
    text = f"`{env.win}/b.R:9`"
    result = env.scan(text)
    assert result.text == text
    assert result.files[0]["path"] == env.path("b.R")
    assert result.files[0]["line"] == 9
    assert result.files[0]["via"] == ["code"]
    assert result.files[0]["texts"] == [env.win + "/b.R:9"]


def test_inline_code_with_two_paths_is_not_a_file(env):
    text = f"`{env.win}/chart.png {env.win}/b.R`"
    result = env.scan(text)
    assert result.files == [] and result.text == text


def test_inline_code_that_is_a_command_is_not_a_file(env):
    for text in ("`git status`", "`D:/a.png D:/b.png`", "`[x](D:/a.png)`"):
        assert env.scan(text).files == []


def test_code_blocks_keep_their_words_and_are_not_files(env):
    text = (f"```\n[a]({env.posix}/chart.png)\n{env.win}/b.R\n"
            f'<img src="{env.win}/chart.png">\n```\n\n'
            f"    [b]({env.posix}/chart.png)\n")
    result = env.scan(text)
    assert result.text == text
    assert result.files == [] and result.notes == []


def test_body_path_needs_an_existing_file(env):
    text = f"看 {env.win}/chart.png。再看 {env.win}/missing.png 和 {env.posix}/nope.md"
    result = env.scan(text)
    assert result.text == text
    assert len(result.files) == 1
    assert result.files[0]["path"] == env.path("chart.png")
    assert result.files[0]["via"] == ["path"]
    assert result.files[0]["texts"] == [env.win + "/chart.png"]


def test_body_path_stops_at_chinese_punctuation(env):
    for tail in ("，", "。", "；", "：", "、", "！", "？", "」", "』", "）", "】", "》", ","):
        result = env.scan(f"文件在 {env.win}/chart.png{tail}")
        assert [row["path"] for row in result.files] == [env.path("chart.png")], tail


def test_body_path_with_spaces_only_inside_quotes(env):
    spaced = env.win + "/space name.txt"
    quoted = env.scan(f"文件在「{spaced}」")
    assert quoted.files[0]["path"] == env.path("space name.txt")
    assert quoted.files[0]["texts"] == [spaced]
    assert env.scan(f"文件在 {spaced}").files == []
    straight = env.scan(f'文件在 "{spaced}"')
    assert straight.files[0]["path"] == env.path("space name.txt")


def test_body_path_with_line_number(env):
    result = env.scan(f"看 {env.win}/b.R:12")
    assert result.files[0]["path"] == env.path("b.R")
    assert result.files[0]["line"] == 12
    assert result.files[0]["texts"] == [env.win + "/b.R:12"]


def test_body_path_inside_a_link_destination_is_not_a_path(env):
    result = env.scan(f"[x]({env.posix}/chart.png)")
    assert [row["via"] for row in result.files] == [["link"]]


def test_files_merge_via_and_texts(env):
    text = f'[a]({env.posix}/chart.png) `{env.win}/chart.png` <img src="{env.win}/chart.png">'
    result = env.scan(text)
    assert len(result.files) == 1
    row = result.files[0]
    assert row["via"] == ["link", "code", "image"]
    assert row["texts"] == [env.win + "/chart.png"]
    assert row["index"] == 0


def test_relative_lookup_order(env):
    first = env.root / "first"
    second = env.root / "second"
    first.mkdir()
    second.mkdir()
    make(first, "same.txt")
    make(second, "same.txt")
    make(env.root / "elsewhere", "only.txt")
    found = env.scan("[x](same.txt)", bases=[str(first), str(second)])
    assert found.files[0]["path"] == str(first / "same.txt")
    later = env.scan("[x](same.txt)", bases=[str(env.root / "none"), str(second)])
    assert later.files[0]["path"] == str(second / "same.txt")
    missing = env.scan("[x](only.txt)", bases=[str(first), str(second)])
    assert missing.files == []
    assert missing.notes == [{"href": "only.txt", "reason": "not_found"}]


def test_relative_missing_file_gets_not_found_note(env):
    result = env.scan("[旧图](out/old.png)")
    assert result.text == "[旧图](out/old.png)"
    assert result.notes == [{"href": "out/old.png", "reason": "not_found"}]


def test_network_and_foreign_paths_never_get_stat(env):
    links = [r"\\server\share\a.png", r"\\wsl$\Ubuntu\home\a.png",
             r"\\wsl.localhost\Ubuntu\home\a.png", r"\\?\UNC\server\share\a.png",
             "file://server/share/a.png",
             "/home/me/a.png", "/Users/me/a.png", "/tmp/a.png"]
    calls = []

    def guard(path):
        calls.append(str(path))
        raise AssertionError(path)

    result = env.scan(" ".join(f"[x]({link})" for link in links), stat=guard)
    assert calls == []
    assert [note["reason"] for note in result.notes] == ["not_local"] * len(links)
    assert result.files == []


def test_web_anchors_mail_and_other_schemes_are_not_files(env):
    for link in ("https://example.com/a.png", "http://localhost:3000/a",
                 "http://127.0.0.1:3000/a", "http://[::1]:3000/a", "#top",
                 "mailto:a@b.c", "vscode://file/D:/a.png", "javascript:alert(1)",
                 "data:text/plain,x"):
        text = f"[x]({link})"
        result = env.scan(text)
        assert result.text == text
        assert result.files == [] and result.notes == [], link


def test_url_with_port_is_not_a_file(env):
    for link in ("https://api.example.com:443", "http://example.com:8080/x/y",
                 "vscode://file/D:/a/fig.png"):
        text = f"[api]({link})"
        result = env.scan(text)
        assert result.text == text
        assert result.files == [] and result.notes == [], link


def test_protocol_relative_web_address_is_not_network(env):
    for text in ("[cdn](//cdn.example.com/a.js)",
                 '<img src="//cdn.example.com/a.js">',
                 '<a href="//cdn.example.com/a.js">x</a>'):
        result = env.scan(text)
        assert result.text == text
        assert result.files == [] and result.notes == [], text


def test_unc_paths_are_still_network(env):
    calls = []

    def guard(path):
        calls.append(path)
        raise AssertionError(path)

    text = (r"[a](\\server\share\a.png) "
            r'<img src="\\wsl$\Ubuntu\home\a.png">')
    result = env.scan(text, stat=guard)
    assert calls == []
    assert result.files == []
    assert result.notes == [{"href": r"\\server\share\a.png", "reason": "not_local"},
                            {"href": r"\\wsl$\Ubuntu\home\a.png", "reason": "not_local"}]


def test_real_paths_are_not_percent_decoded(env):
    name = "b%20c.png"
    path = env.path(name)
    presented = env.scan("答案", presented=[path])
    assert presented.files[0]["path"] == path
    citation = env.scan(f':codex-file-citation{{path="{path}"}}')
    assert citation.files[0]["path"] == path
    code = env.scan(f"`{path}`")
    assert code.files[0]["path"] == path
    body = env.scan(f"看 {path}。")
    assert body.files[0]["path"] == path
    # Markdown links and images are URLs and still decode once.
    markdown = env.scan("[x](b%2520c.png)")
    assert markdown.files[0]["path"] == path
    assert markdown.text == f"[x](<{env.posix}/b%2520c.png>)"


def test_fake_definition_line_keeps_its_link(env):
    text = f"[注]: see [x]({env.posix}/chart.png)"
    result = env.scan(text)
    assert result.text == f"[注]: see [x](<{env.posix}/chart.png>)"
    assert result.files[0]["via"] == ["link"]
    assert "texts" not in result.files[0]
    assert result.notes == []


def test_only_real_definition_lines_are_definitions(env):
    text = (f"[r]\n\n[r]: <{env.posix}/chart.png>\n\n"
            f"[r]: see [x]({env.posix}/b.R)\n")
    result = env.scan(text)
    assert result.text == (f"[r]\n\n[r]: <{env.posix}/chart.png>\n\n"
                           f"[r]: see [x](<{env.posix}/b.R>)\n")
    assert [row["path"] for row in result.files] == [env.path("chart.png"), env.path("b.R")]


def test_paths_in_link_text_are_not_body_paths(env):
    target = env.posix_path("chart.png")
    inline = f"[{env.win}/chart.png 图]({target})"
    result = env.scan(inline)
    assert result.files[0]["via"] == ["link"]
    assert "texts" not in result.files[0]
    assert result.text == f"[{env.win}/chart.png 图](<{target}>)"

    image = f"![{env.win}/chart.png]({target})"
    result = env.scan(image)
    assert result.files[0]["via"] == ["image"]
    assert "texts" not in result.files[0]

    reference = f"[{env.win}/chart.png][r]\n\n[r]: <{target}>\n"
    result = env.scan(reference)
    assert result.files[0]["via"] == ["link"]
    assert "texts" not in result.files[0]


def test_file_autolink_is_recognized_but_not_rewritten(env):
    text = f"<file:///{env.posix}/chart.png>"
    result = env.scan(text)
    assert result.text == text
    assert result.files[0]["path"] == env.path("chart.png")
    assert result.files[0]["via"] == ["link"]
    assert result.files[0]["index"] == 1000
    assert "texts" not in result.files[0]

    missing = f"<file:///{env.posix}/nope.png>"
    result = env.scan(missing)
    assert result.text == missing
    assert result.files[0]["exists"] is False
    assert result.files[0]["index"] == 1000


def test_file_autolink_gets_1000_even_beside_a_markdown_link(env):
    text = f"[a]({env.posix}/b.R) <file:///{env.posix}/chart.png>"
    result = env.scan(text)
    rows = {row["path"]: row for row in result.files}
    assert rows[env.path("b.R")]["index"] == 0
    assert rows[env.path("chart.png")]["index"] == 1000


def test_no_markers_returns_the_text_untouched(env):
    text = "普通回答，没有文件。"
    result = env.scan(text)
    assert result.text == text
    assert result.files == [] and result.notes == []


def test_contract_with_three_clients(env):
    wsl = "/mnt/" + env.posix[0].lower() + env.posix[2:]
    parts = [
        f"[a]({env.win}/chart.png)",
        f"[b](file:///{env.posix}/chart.png)",
        f"[c]({wsl}/chart.png)",
        f"[d](~/docs/home.txt)",
        f"[e](src/app.ts:12)",
        f"[f]({env.posix}/100%25.txt)",
        f"![g](<{env.posix}/报告 图 (1).png>)",
        f"[h]({env.posix}/out/report.md#L12)",
        f"[i]({env.posix}/sub/.hidden/f.md)",
        f"[j]({env.posix}/missing.png)",
        f"[k]({env.posix}/folder)",
    ]
    result = env.scan(" ".join(parts))
    addresses = re.findall(r"<([A-Za-z]:[\\/][^>]*)>", result.text)
    assert len(addresses) == len(parts)
    known = {normalized(row["path"]) for row in result.files}
    for address in addresses:
        android = android_local(address)
        ios = ios_local(address)
        assert android is not None, address
        assert ios is not None, address
        assert web_local(address), address
        assert normalized(android) == normalized(ios)
        assert normalized(android) in known, address


def test_idempotent(env):
    text = (f"[a]({env.win}/chart.png) ![i](<{env.posix}/space name.txt>) "
            f"[missing](out/old.png) [net](\\\\server\\share\\a.png) "
            f"`{env.win}/b.R` 看 {env.win}/src/app.ts。\n\n"
            f"```\n[x]({env.posix}/chart.png)\n```\n")
    first = env.scan(text)
    second = env.scan(first.text)
    assert second.text == first.text
    assert [row["path"] for row in second.files] == [row["path"] for row in first.files]
    assert [row["indexes"] for row in second.files] == [row["indexes"] for row in first.files]
    assert second.notes == first.notes


def test_unknown_percent_sequence_stays_as_written(env):
    make(env.root, "%FF.txt")
    result = env.scan("[x](%FF.txt)")
    assert result.files[0]["path"] == env.path("%FF.txt")
    assert result.text == f"[x](<{env.posix}/%25FF.txt>)"


def test_at_most_fifty_files(env):
    text = " ".join(f"[x]({env.posix}/missing-{index}.png)" for index in range(60))
    result = env.scan(text)
    assert len(result.files) == 50
    assert result.files[0]["indexes"] == [0]
    assert result.files[49]["indexes"] == [49]


def test_empty_input(env):
    for value in ("", None):
        result = env.scan(value)
        assert result.text == (value or "")
        assert result.files == [] and result.notes == []
