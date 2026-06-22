"""Pure-function tests for font helpers — no PDF fixture required."""
from pdfkit.fonts import parse_tounicode


def _cmap(body: str) -> bytes:
    return (
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        "1 begincodespacerange\n<0000><ffff>\nendcodespacerange\n"
        f"{body}\nendcmap\nend\nend\n"
    ).encode("latin-1")


def test_parse_tounicode_bfrange_array():
    # Array-form bfrange: <lo> <hi> [ <v0> <v1> ... ] maps code+i -> v_i.
    # Real sample from a Chromium/Skia subset (Eric_Cantona_Resume.pdf): the
    # greedy triple form used to mis-read this, decoding GID 1 as 'S' not 'E'.
    body = (
        "1 beginbfrange\n"
        "<0000> <0005> [<0000> <0045> <0052> <0049> <0043> <0020>]\n"
        "endbfrange"
    )
    m = parse_tounicode(_cmap(body))
    assert [m.get(i) for i in range(1, 6)] == ["E", "R", "I", "C", " "]


def test_parse_tounicode_incremental_bfrange_still_works():
    # The non-array (incremental) form must keep working unchanged.
    body = "1 beginbfrange\n<0041> <0043> <0061>\nendbfrange"
    m = parse_tounicode(_cmap(body))
    assert (m[0x41], m[0x42], m[0x43]) == ("a", "b", "c")


def test_parse_tounicode_bfchar():
    body = "1 beginbfchar\n<0007> <0041>\nendbfchar"
    assert parse_tounicode(_cmap(body))[7] == "A"
