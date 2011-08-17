# coding: utf8

#  WeasyPrint converts web documents (HTML, CSS, ...) to PDF.
#  Copyright (C) 2011  Simon Sapin
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

import contextlib

from attest import Tests, assert_hook

from ..css.values import get_single_keyword
from ..css import validation
from ..document import Document
from ..formatting_structure import boxes
from ..formatting_structure import build


suite = Tests()


def serialize(box_list):
    """
    Transform a box list into a structure easier to compare for testing.
    """
    types = {
        boxes.TextBox: 'text',
        boxes.LineBox: 'line',
        boxes.BlockBox: 'block',
        boxes.InlineBox: 'inline',
        boxes.InlineBlockBox: 'inline_block',
        boxes.AnonymousBlockBox: 'anon_block',
        boxes.InlineLevelReplacedBox: 'inline_replaced',
    }
    return [
        (box.element.tag, types[box.__class__], (
            # All concrete boxes are either text, replaced or parent.
            box.text if isinstance(box, boxes.TextBox)
            else '<replaced>' if isinstance(box, boxes.ReplacedBox)
            else serialize(box.children)))
        for box in box_list
    ]


def unwrap_html_body(box):
    """
    Test that the box tree starts with an <html> block and a <body> block
    and remove them to simplify further tests. These are always at the root
    of HTML documents.
    """
    assert box.element.tag == 'html'
    assert isinstance(box, boxes.BlockBox)
    assert len(box.children) == 1

    box = box.children[0]
    assert isinstance(box, boxes.BlockBox)
    assert box.element.tag == 'body'

    return box.children


def to_lists(box_tree):
    """Serialize and unwrap <html> and <body>."""
    return serialize(unwrap_html_body(box_tree))


@contextlib.contextmanager
def monkeypatch_validation(replacement):
    real_non_shorthand = validation.validate_non_shorthand

    def patched_non_shorthand(*args, **kwargs):
        return replacement(real_non_shorthand, *args, **kwargs)

    validation.validate_non_shorthand = patched_non_shorthand
    try:
        yield
    finally:
        validation.validate_non_shorthand = real_non_shorthand


def validate_inline_block(real_non_shorthand, name, values, required=False):
    if name == 'display' and get_single_keyword(values) == 'inline-block':
        return [(name, values)]
    return real_non_shorthand(name, values, required)


def parse(html_content):
    """
    Parse some HTML, apply stylesheets and transform to boxes.
    """
    # TODO: remove this patching when inline-block is validated.
    with monkeypatch_validation(validate_inline_block):
        document = Document.from_string(html_content)
        return build.dom_to_box(document, document.dom)


def prettify(tree_list):
    """Special formatting for printing serialized box trees."""
    def lines(tree, indent=0):
        tag, type_, content = tree
        if type_ in ('text', 'inline_replaced'):
            yield '%s%s %s %r' % ('    ' * indent, tag, type_, content)
        else:
            yield '%s%s %s' % ('    ' * indent, tag, type_)
            for child in content:
                for line in lines(child, indent + 1):
                    yield line

    return '\n'.join(line for tree in tree_list for line in lines(tree))


def assert_tree(box, expected):
    """
    Test box tree equality with the prettified obtained result in the message
    in case of failure.

    box: a Box object, starting with <html> and <body> blocks.
    expected: a list of serialized <body> children as returned by to_lists().
    """
    result = to_lists(box)
    assert result == expected, 'Got\n' + prettify(result)


@suite.test
def test_box_tree():
    assert_tree(parse('<p>'), [('p', 'block', [])])
    assert_tree(parse('''
        <style>
            span { display: inline-block }
        </style>
        <p>Hello <em>World <img src="foo.png"><span>Lipsum</span></em>!</p>
    '''), [
        ('p', 'block', [
            ('p', 'text', 'Hello '),
            ('em', 'inline', [
                ('em', 'text', 'World '),
                ('img', 'inline_replaced', '<replaced>'),
                ('span', 'inline_block', [
                    ('span', 'text', 'Lipsum')])]),
            ('p', 'text', '!')])])


@suite.test
def test_html_entities():
    for quote in ['"', '&quot;', '&#x22;', '&#34;']:
        assert_tree(parse('<p>{}abc{}'.format(quote, quote)), [
            ('p', 'block', [
                ('p', 'text', '"abc"')])])


@suite.test
def test_inline_in_block():
    source = '<div>Hello, <em>World</em>!\n<p>Lipsum.</p></div>'
    expected = [
        ('div', 'block', [
            ('div', 'anon_block', [
                ('div', 'line', [
                    ('div', 'text', 'Hello, '),
                    ('em', 'inline', [
                        ('em', 'text', 'World')]),
                    ('div', 'text', '!\n')])]),
            ('p', 'block', [
                ('p', 'line', [
                    ('p', 'text', 'Lipsum.')])])])]

    box = parse(source)
    box = build.inline_in_block(box)
    assert_tree(box, expected)

    box = parse(source)
    # This should be idempotent: doing more than once does not change anything.
    box = build.inline_in_block(box)
    box = build.inline_in_block(box)
    assert_tree(box, expected)


@suite.test
def test_block_in_inline():
    box = parse('''
<style>
    p { display: inline-block; }
    span { display: block; }
</style>
<p>Lorem <em>ipsum <strong>dolor <span>sit</span>
    <span>amet,</span></strong><span><em>consectetur<div/></em></span></em></p>
    ''')
    box = build.inline_in_block(box)
    assert_tree(box, [
        ('body', 'line', [
            ('p', 'inline_block', [
                ('p', 'line', [
                    ('p', 'text', 'Lorem '),
                    ('em', 'inline', [
                        ('em', 'text', 'ipsum '),
                        ('strong', 'inline', [
                            ('strong', 'text', 'dolor '),
                            ('span', 'block', [ # This block is "pulled up"
                                ('span', 'line', [
                                    ('span', 'text', 'sit')])]),
                            # No whitespace processing here.
                            ('strong', 'text', '\n    '),
                            ('span', 'block', [ # This block is "pulled up"
                                ('span', 'line', [
                                    ('span', 'text', 'amet,')])])]),
                        ('span', 'block', [ # This block is "pulled up"
                            ('span', 'line', [
                                ('em', 'inline', [
                                    ('em', 'text', 'consectetur'),
                                    ('div', 'block', []),
                                    ])])])])])])])])

    box = build.block_in_inline(box)
    assert_tree(box, [
        ('body', 'line', [
            ('p', 'inline_block', [
                ('p', 'anon_block', [
                    ('p', 'line', [
                        ('p', 'text', 'Lorem '),
                        ('em', 'inline', [
                            ('em', 'text', 'ipsum '),
                            ('strong', 'inline', [
                                ('strong', 'text', 'dolor ')])])])]),
                ('span', 'block', [
                    ('span', 'line', [
                        ('span', 'text', 'sit')])]),
                ('p', 'anon_block', [
                    ('p', 'line', [
                        ('em', 'inline', [
                            ('strong', 'inline', [
                                # Whitespace processing not done yet.
                                ('strong', 'text', '\n    ')])])])]),
                ('span', 'block', [
                    ('span', 'line', [
                        ('span', 'text', 'amet,')])]),

                ('p', 'anon_block', [
                    ('p', 'line', [
                        ('em', 'inline', [
                            ('strong', 'inline', [])])])]),
                ('span', 'block', [
                    ('span', 'anon_block', [
                        ('span', 'line', [
                            ('em', 'inline', [
                                ('em', 'text', 'consectetur')])])]),
                    ('div', 'block', []),
                    ('span', 'anon_block', [
                        ('span', 'line', [
                            ('em', 'inline', [])])])]),
                ('p', 'anon_block', [
                    ('p', 'line', [
                        ('em', 'inline', [])])])])])])


@suite.test
def test_styles():
    box = parse('''
        <style>
            span { display: block; }
            * { margin: 42px }
            html { color: blue }
        </style>
        <p>Lorem <em>ipsum <strong>dolor <span>sit</span>
            <span>amet,</span></strong><span>consectetur</span></em></p>''')
    box = build.inline_in_block(box)
    box = build.block_in_inline(box)

    for child in box.descendants():
        # All boxes inherit the color
        assert child.style.color[0].value == 'blue'
        # Only non-anonymous boxes have margins
        if isinstance(child, boxes.AnonymousBox):
            assert child.style.margin_top[0].value == 0
        else:
            assert child.style.margin_top[0].value == 42


@suite.test
def test_whitespace():
    # TODO: test more cases
    # http://www.w3.org/TR/CSS21/text.html#white-space-model
    document = Document.from_string('''
        <p>Lorem \t\r\n  ipsum\t<strong>  dolor </strong>.</p>
        <pre>\t  foo\n</pre>
        <pre style="white-space: pre-wrap">\t  foo\n</pre>
        <pre style="white-space: pre-line">\t  foo\n</pre>
        ''')
    box = build.build_formatting_structure(document)

    assert_tree(box, [
        ('p', 'block', [
            ('p', 'line', [
                ('p', 'text', 'Lorem ipsum '),
                ('strong', 'inline', [
                    ('strong', 'text', 'dolor ')]),
                ('p', 'text', '.')])]),
        ('body', 'anon_block', [
            ('body', 'line', [
                ('body', 'text', ' ')])]),
        ('pre', 'block', [
            ('pre', 'line', [
                # pre
                ('pre', 'text', u'\t\xA0\xA0foo\n')])]),
        ('body', 'anon_block', [
            ('body', 'line', [
                ('body', 'text', ' ')])]),
        ('pre', 'block', [
            ('pre', 'line', [
                # pre-wrap
                ('pre', 'text', u'\t\xA0\xA0\u200Bfoo\n')])]),
        ('body', 'anon_block', [
            ('body', 'line', [
                ('body', 'text', ' ')])]),
        ('pre', 'block', [
            ('pre', 'line', [
                # pre-line
                ('pre', 'text', u'foo\n')])])])


@suite.test
def test_page_style():
    document = Document.from_string('''
        <style>
            @page { margin: 3px }
            @page :first { margin-top: 20px }
            @page :right { margin-right: 10px; margin-top: 10px }
            @page :left { margin-left: 10px; margin-top: 10px }
        </style>
    ''')
    def assert_page_margins(page_number, top, right, bottom, left):
        page = boxes.PageBox(
            document, boxes.BlockBox(document, document.dom), page_number)
        assert page.style.margin_top[0].value == top
        assert page.style.margin_right[0].value == right
        assert page.style.margin_bottom[0].value == bottom
        assert page.style.margin_left[0].value == left

    # odd numbers are :right pages, even are :left. 1 has :first as well
    assert_page_margins(1, top=20, right=10, bottom=3, left=3)
    assert_page_margins(2, top=10, right=3, bottom=3, left=10)
    assert_page_margins(3, top=10, right=10, bottom=3, left=3)
    assert_page_margins(4, top=10, right=3, bottom=3, left=10)
    assert_page_margins(45, top=10, right=10, bottom=3, left=3)
    assert_page_margins(122, top=10, right=3, bottom=3, left=10)


@suite.test
def test_containing_block():
    """Test the boxes containing block."""
    box = None
#    box = parse('''
#        <html>
#          <style>
#            body { height: 297mm; width: 210mm }
#            p { width: 100mm; height: 200mm }
#            p span { position: absolute }
#            p em { position: relative }
#            li { position: fixed }
#            li span { position: fixed }
#          </style>
#          <body>
#            <p>
#              Lorem <em>ipsum <strong>dolor <span>sit</span>
#              <span>amet,</span></strong><span>consectetur</span></em>
#            </p>
#            <ul>
#              <li>Lorem ipsum dolor sit amet</li>
#              <li>Lorem ipsum <spam>dolor sit amet</span></li>
#            </ul>
#          </body>
#        </html>
#    ''')
#    tree = to_lists(box)