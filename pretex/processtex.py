#!env python3

# TODO: empty groups


import argparse
import os
import re
import sys
from base64 import b64encode
from hashlib import md5
from io import StringIO
from shutil import move
from subprocess import Popen, PIPE
from tempfile import TemporaryDirectory

from lxml import html

import simpletransform


BASE = os.path.dirname(__file__)
TOUNICODE = os.path.join(BASE, 'tounicode.py')

PID = os.getpid()

import platform
if platform.system() == 'Darwin':
    FONTFORGE = '/Applications/FontForge.app/Contents/Resources/opt/local/bin/fontforge'
else:
    FONTFORGE = 'fontforge'

def log(text):
    print("[{:6d}] {}".format(PID, text))

# Snippet to tell fontforge to delete some empty lists.
# Otherwise the Webkit CFF sanitizer balks.
# Also, FF seems to incorrectly save default values for some entries.
FIX_PRIVATE_TABLE = '''
  if(GetPrivateEntry("OtherBlues") == "[]")
     ClearPrivateEntry("OtherBlues")
  endif
  if(GetPrivateEntry("FamilyBlues") == "[]")
     ClearPrivateEntry("FamilyBlues")
  endif
  if(GetPrivateEntry("FamilyOtherBlues") == "[]")
     ClearPrivateEntry("FamilyOtherBlues")
  endif
  if(GetPrivateEntry("BlueShift") == "")
     ChangePrivateEntry("BlueShift", "7")
  endif
  if(GetPrivateEntry("BlueScale") == "")
     ChangePrivateEntry("BlueScale", ".039625")
  endif
  if(GetPrivateEntry("BlueFuzz") == "")
     ChangePrivateEntry("BlueFuzz", "1")
  endif
'''

LATEX_PREAMBLE = r'''
\documentclass[12pt,reqno]{amsart}
\usepackage[margin=0pt]{geometry}
\usepackage[charter,sfscaled,ttscaled,cal=cmcal]{mathdesign}
\renewcommand{\sfdefault}{phv}
\usepackage{textcomp}

\newwrite\boxsize
\immediate\openout\boxsize=boxsize.txt
\def\writesize#1{\write\boxsize{#1}}
\newsavebox\measurebox

\newlength\emlength

\def\postag#1{\tag*{\phantom{#1}\pdfsavepos\write\boxsize{tag:{#1},\the\pdflastypos}}}

\pagestyle{empty}

\usepackage{graphicx}
\graphicspath{{figure-images/}{.}}
'''

LATEX_BEGIN = r'''
\begin{document}%
\topskip=0pt%
\parindent=0pt%
\parskip=0pt%
\thispagestyle{empty}%
\emlength=1em\writesize{fontsize:\the\emlength}%
'''

LATEX_NEWPAGE = r'\newpage\topskip=0pt%' + '\n'

LATEX_INLINE = r'''%
\sbox{{\measurebox}}{{%
${code}$%
}}%
\vbox to 0pt{{\vss\usebox\measurebox}}%
\writesize{{inline:{{\the\wd\measurebox}}{{\the\ht\measurebox}}{{\the\dp\measurebox}}}}%
'''

LATEX_CODE_INLINE = r'''%
\sbox{{\measurebox}}{{%
{code}%
}}%
\vbox to 0pt{{\vss\usebox\measurebox}}%
\writesize{{inline:{{\the\wd\measurebox}}{{\the\ht\measurebox}}{{\the\dp\measurebox}}}}%
'''

# tounicode.py calculates the extents for displayed equations
# html is 675px ~ 7in wide
LATEX_DISPLAY = r'''%
\pdfsavepos\write\boxsize{{prepage:\the\pdflastypos}}
\begin{{minipage}}{{7in}}%
{code}%
\end{{minipage}}%
\writesize{{display:}}%
'''

PRETEX_STYLE = '''
.pretex-bind {
  display: inline-block;
}
.pretex-inline {
  display: inline-block;
}
.pretex-inline span {
  display: inline-block;
}
.pretex-inline span:last-child {
  position: relative;
}
.pretex-inline span:last-child svg.pretex {
  position: absolute;
  bottom:   0;
  height:   1em;
}
svg.pretex {
  display:      inline-block;
  overflow:     visible;
  font-variant: normal;
  font-weight:  normal;
  font-style:   normal;
}
.pretex-display {
  text-align:  center;
  margin:      1em 0;
  padding:     0;
  text-indent: 0;
  text-transform: none;
  position: relative;
}
.pretex-display svg.pretex {
  /* hack to adjust spacing */
  vertical-align: middle;
}
.pretex-display .tag {
  position:    absolute;
  right:       0;
  top:         0;
}
.pretex-display .tag > span {
  display: inline-block;
}
'''

# This is where processed images end up under build/
FIGURE_IMG_DIR = 'figure-images'


def check_proc(proc, msg='', stdin=None):
    "Run a process and die verbosely on error."
    if stdin is not None:
        stdin = stdin.encode('ascii')
    out, err = proc.communicate(input=stdin)
    if proc.returncode != 0:
        print(msg)
        print("stdout:")
        print(out.decode())
        print("stderr:")
        print(err.decode())
        sys.exit(1)
    return out

def css_to_dict(css_str):
    "Simple parser."
    # Won't handle complicated things like semicolons in strings.
    ret = {}
    for line in css_str.split(';'):
        idx = line.find(':')
        if idx == -1:
            continue
        key = line[:idx].strip()
        val = line[idx+1:].strip()
        if val[0] == "'" or val[0] == '"':
            val = val[1:-1]
        else:
            # Assume whitespace is unimportant in unquoted values
            val = val.replace(' ', '')
        ret[key] = val
    return ret

def dict_to_css(css):
    items = []
    for key, val in css.items():
        if val.find(' ') != -1:
            val = "'" + val + "'"
        items.append(key + ':' + val)
    return ';'.join(items)

def smart_float(num, decimals=5):
    return format(num, "." + str(decimals) + 'f').rstrip('0').rstrip('.')

# Encoding an md5 digest in base64 instead of hex reduces length from 32 to 20
def b64_hash(text):
    if not isinstance(text, bytes):
        text = text.encode()
    return b64encode(md5(text).digest()[:15], b'-_').decode('ascii')


class CSSClasses:
    """
    Some style attributes, like stroke-width, font-size, and font-family,
    require many characters to specify, despite there being few unique values.
    It saves space to use css classes with short names for these.  This class
    acts as a repository for such css classes.
    """
    def __init__(self):
        self.class_names = {}
        self.class_vals = {}
    def get(self, val):
        if val in self.class_vals:
            return self.class_vals[val]
        class_name = 'c' + b64_hash(val)[:4]
        self.class_names[class_name] = val
        self.class_vals[val] = class_name
        return class_name
    def css(self, prefix):
        return ''.join(prefix + '.' + name + '{' + val + '}'
                       for name,val in self.class_names.items()) + '\n'


class HTMLDoc:
    """
    Stores all data needed to convert the LaTeX in an html file.
    """

    SVG_ATTRS = set(['viewBox', 'height', 'width', 'version'])

    DEFAULT_TEXT = css_to_dict('''
        writing-mode: lr-tb;
        fill:         #000000;
        fill-rule:    nonzero;
        fill-opacity: 1;
        stroke:       none;
    ''')
    DEFAULT_PATH = css_to_dict('''
        fill:              none;
        fill-rule:         nonzero;
        fill-opacity:      1;
        stroke:            #000000;
        stroke-linecap:    butt;
        stroke-linejoin:   miter;
        stroke-miterlimit: 10;
        stroke-dasharray:  none;
        stroke-opacity:    1;
    ''')

    def __init__(self, html_file, preamble, tmp_dir, cache_dir, img_dir):
        self.html_file = html_file
        with open(self.html_file) as fobj:
            self.html_data = fobj.read()
        parser = html.HTMLParser(remove_comments=True)
        self.dom = html.parse(StringIO(self.html_data), parser=parser)
        self.to_replace = []
        self.preamble = preamble
        self.basename = b64_hash(self.html_data)
        self.base_dir = os.path.join(tmp_dir, self.basename)
        self.pdf_dir = os.path.join(self.base_dir, 'pdf')
        self.svg_dir = os.path.join(self.base_dir, 'svg')
        self.out_img_dir = os.path.join(tmp_dir, 'img')
        self.cache_dir = cache_dir

        os.makedirs(self.base_dir, exist_ok=True)
        os.makedirs(self.pdf_dir, exist_ok=True)
        os.makedirs(self.svg_dir, exist_ok=True)
        link_dest = os.path.join(self.pdf_dir, 'figure-images')
        if not os.path.exists(link_dest):
            os.symlink(os.path.realpath(img_dir), link_dest,
                       target_is_directory=True)

        self.latex_file = os.path.join(self.pdf_dir, self.basename + '.tex')
        self.pdf_file = os.path.join(self.pdf_dir, self.basename + '.pdf')
        self.boxsize_file = os.path.join(self.pdf_dir, 'boxsize.txt')
        self.pages_extents = []
        self.num_pages = 0
        self.fonts = {}
        self.font_hashes = {}
        self.images = []
        self.contents = ''
        self.html_cache = None
        self.path_classes = CSSClasses()
        self.tspan_classes = CSSClasses()

    @property
    def is_cached(self):
        return os.path.exists(self.html_cache)

    def svg_file(self, num):
        return os.path.join(self.svg_dir, 'out{:03d}.svg'.format(num+1))

    def make_latex(self):
        "Extract math from the html file, then make a LaTeX file."
        self.to_replace = []
        pages = []
        for elt in self.dom.getiterator('script'):
            if not elt.attrib.get('type', '').startswith('text/x-latex-'):
                continue
            if not elt.text:
                continue
            code = elt.text.strip()
            typ = elt.attrib['type']
            if typ == 'text/x-latex-inline':
                pages.append(LATEX_INLINE.format(code=code))
                pages.append(LATEX_NEWPAGE)
            elif typ == 'text/x-latex-code-inline':
                pages.append(LATEX_CODE_INLINE.format(code=code))
                pages.append(LATEX_NEWPAGE)
            elif typ == 'text/x-latex-code-bare':
                # Use raw code
                pages.append(code)
                continue
            elif typ in ('text/x-latex-display', 'text/x-latex-code'):
                if code.find(r'\tag') != -1:
                    code = code.replace(r'\tag', r'\postag')
                pages.append(LATEX_DISPLAY.format(code=code, pageno=len(pages)))
                pages.append(LATEX_NEWPAGE)
            self.to_replace.append(elt)
        if not pages:
            return False
        if pages[-1] == LATEX_NEWPAGE:
            pages = pages[:-1]
        contents = ''
        with open(self.latex_file, 'w') as fobj:
            fobj.write(LATEX_PREAMBLE)
            fobj.write(self.preamble)
            fobj.write(LATEX_BEGIN)
            fobj.write(''.join(pages))
            fobj.write(r'\end{document}')
            contents += LATEX_PREAMBLE
            contents += self.preamble
            contents += LATEX_BEGIN
            contents += ''.join(pages)
            contents += r'\end{document}'
        # Now we know the hash file name
        self.html_cache = os.path.join(self.cache_dir, b64_hash(contents))
        self.contents = contents
        return True

    def latex(self):
        "Compile the file generated by self.make_latex()"
        proc = Popen(['pdflatex', '-interaction=nonstopmode',
                      '\\input{' + os.path.basename(self.latex_file) + '}'],
                     cwd=self.pdf_dir, stdout=PIPE, stderr=PIPE)
        check_proc(proc, 'Failed to compile LaTeX in {}'.format(
            self.html_file) + '\n'
                   + 'Contents of .tex file:\n'
                   + self.contents)

    def read_extents(self):
        "Parse boxsize.txt and populate size data."
        self.pages_extents = []
        this_prepage = 0
        this_tags = []
        fontsize = 12
        with open(self.boxsize_file) as fobj:
            for line in fobj.readlines():
                if line.startswith('fontsize:'):
                    # Should be the first line; ends in "pt\n"
                    # Convert to big (usual) points
                    fontsize = float(line[len('fontsize:'):-3]) * 800/803
                    continue
                if line.startswith('prepage:'):
                    # Position of the top of the page (relative to the bottom)
                    this_prepage = float(line[len('prepage:'):])
                    continue
                if line.startswith('tag:'):
                    line = line[len('tag:'):]
                    match = re.match(r'{(.*)},(.*)', line)
                    if not match:
                        continue
                    contents, pos = match.groups()
                    # Position of a tag on the page
                    pos = this_prepage - float(pos)
                    # This is in in sp = 1/65536 pt
                    pos /= 65536
                    pos *= 800/803
                    this_tags.append((contents, pos))
                    continue
                match = re.match(
                    r'inline:{(.*)pt}{(.*)pt}{(.*)pt}', line)
                if match:
                    typ = 'inline'
                    width, height, depth = [float(x) for x in match.groups()]
                    # Convert to big point (everyone else's points): * 800 / 803
                    width *= 800/803
                    height *= 800/803
                    depth *= 800/803
                    left = 0
                    top = -height
                else:
                    match = re.match(r'display:(.*),(.*),(.*),(.*)', line)
                    if not match:
                        continue
                    typ = 'display'
                    left, top, width, height \
                        = [float(x) for x in match.groups()]
                    depth = 0
                    this_tags = [(c, y - top) for c, y in this_tags]
                # In Inkscape, 96 user units (or "px") is one inch, which is 72
                # pt.  The "width", "height", and "depth" are used to specify
                # the viewBox, which is in user units.
                page_extents = {
                    "width"  : width  * 96/72,
                    "height" : height * 96/72,
                    "left"   : left   * 96/72,
                    "top"    : top    * 96/72,
                    "depth"  : depth  * 96/72,
                    "tags"   : this_tags,
                    # These are used for the "width", "height", and
                    # "vertical-align" properties, which are relative to the
                    # current font size.
                    "fontsize" : fontsize,
                    "widthem"  : width  / fontsize,
                    "heightem" : height / fontsize,
                    "depthem"  : depth  / fontsize,
                    "display"  : typ == 'display',
                }
                self.pages_extents.append(page_extents)
                this_tags = []
                this_prepage = 0
        self.num_pages = len(self.pages_extents)
        self.DEFAULT_TEXT['font-size'] = "{}px".format(fontsize)

    def inkscape_script(self):
        "Generate inkscape commands necessary to convert pdf to svg."
        script = ''
        for page_num in range(self.num_pages):
            script += '--file="{}" --pdf-page={}' \
                      ' --export-plain-svg="{}"\n' \
                      .format(self.pdf_file, page_num+1,
                              self.svg_file(page_num))
        return script

    def add_font(self, name, fname):
        with open(fname, 'rb') as fobj:
            self.fonts[name] = fobj.read()
        self.font_hashes[name] = 'f'+b64_hash(self.fonts[name])[:4]

    def write_cache(self, style, fonts, svgs):
        "Cache the computed data in an xml file"
        cache = html.Element('cache')
        elt = html.Element('style', id='pretex-style')
        elt.text = style
        cache.append(elt)
        elt = html.Element('style', id='pretex-fonts')
        elt.text = fonts
        cache.append(elt)
        for svg in svgs:
            svg.tail = ''
            cache.append(svg)
        with open(self.html_cache, 'wb') as fobj:
            fobj.write(html.tostring(cache))

    def _replace_elt(self, elt, svg):
        "Replace an element with an svg, using a binding wrapper if necessary."
        # The code below is to prevent a line break occurring between an
        # equation and an adjacent piece of text, like "ith" or "(and f(x))".
        if svg.attrib['class'] == 'pretex-inline':
            head_text = ''
            tail_text = elt.tail
            need_wrap = False
            if elt.tail and not elt.tail[0].isspace():
                match = re.match(r'(\S+)(.*)', elt.tail)
                svg.tail, tail_text = match.groups()
                need_wrap = True
            # Figure out what text came right before this element
            prev = elt.getprevious()
            parent = elt.getparent()
            if prev is not None and prev.tail and not prev.tail[-1].isspace():
                match = re.match(r'(.*\s)?(\S+)', prev.tail)
                unbound, head_text = match.groups()
                prev.tail = unbound or ''
                need_wrap = True
            elif prev is None and parent.text and not parent.text[-1].isspace():
                match = re.match(r'(.*\s)?(\S+)', parent.text)
                unbound, head_text = match.groups()
                parent.text = unbound or ''
                need_wrap = True
            if need_wrap:
                # Wrap in a binding span
                wrapper = html.Element('span', {'class' : 'pretex-bind'})
                wrapper.text = head_text
                wrapper.append(svg)
                wrapper.tail = tail_text
                svg = wrapper
            else:
                svg.tail = tail_text
        elt.getparent().replace(elt, svg)

    def use_cached(self, outfile):
        "Write the cached output to the html file."
        with open(self.html_cache, 'rb') as fobj:
            cache = html.fromstring(fobj.read())
        style = cache[0].text
        fonts = cache[1].text
        # Replace DOM elements
        for elt in self.to_replace:
            svg = cache[2]
            self._replace_elt(elt, svg)
        root = self.dom.getroot()
        try:
            root.get_element_by_id('pretex-style').text = style
        except KeyError:
            pass
        try:
            root.get_element_by_id('pretex-fonts').text = fonts
        except KeyError:
            pass
        for elt in self.dom.getiterator('script'):
            if elt.attrib.get('type', '').startswith('text/x-latex-code-bare'):
                elt.getparent().remove(elt)
        with open(outfile, 'wb') as outf:
            outf.write(html.tostring(
                self.dom, include_meta_content_type=True, encoding='utf-8'))

    def write_html(self, outfile):
        svgs = self.process_svgs()
        cached_elts = []
        # Replace DOM elements
        for i, elt in enumerate(self.to_replace):
            self._replace_elt(elt, svgs[i])
            cached_elts.append(svgs[i])
        style = PRETEX_STYLE
        style += r'''
        svg.pretex text {{
          {}
        }}
        svg.pretex path {{
          {}
        }}'''.format(
            dict_to_css(self.DEFAULT_TEXT), dict_to_css(self.DEFAULT_PATH))
        root = self.dom.getroot()
        try:
            root.get_element_by_id('pretex-style').text = style
        except KeyError:
            pass
        # Add fonts
        font_style = ''
        for name, data in self.fonts.items():
            name = self.font_hashes[name]
            font_style += r'''
            @font-face {{
              font-family: "{name}";
              src: url(data:application/font-woff;base64,{data}) format('woff');
            }}'''.format(name=name, data=b64encode(data).decode('ascii'))
        # These go here so they show up in knowls too
        font_style += self.tspan_classes.css('svg.pretex tspan')
        font_style += self.path_classes.css('svg.pretex path')
        font_style += ''.join('svg.pretex tspan.' + h + '{font-family:' + h + '}'
                              for h in self.font_hashes.values())
        try:
            root.get_element_by_id('pretex-fonts').text = font_style
        except KeyError:
            pass
        for elt in self.dom.getiterator('script'):
            if elt.attrib.get('type', '').startswith('text/x-latex-code-bare'):
                elt.getparent().remove(elt)
        with open(outfile, 'wb') as outf:
            outf.write(html.tostring(
                self.dom, include_meta_content_type=True, encoding='utf-8'))
        self.write_cache(style, font_style, cached_elts)

    def process_svgs(self):
        "Process all generated svgs file for use in an html page."
        svgs = []
        for page_num, page_extents in enumerate(self.pages_extents):
            with open(self.svg_file(page_num), 'rb') as fobj:
                svg = html.fromstring(fobj.read())
            # Remove extra attrs from <svg>
            for key in svg.attrib.keys():
                if key not in self.SVG_ATTRS:
                    del svg.attrib[key]
            # Auto-calculated based on height and viewBox aspect ratio
            del svg.attrib['width']
            svg.attrib['class'] = 'pretex'
            # Get rid of metadata
            metadata = svg.find('metadata')
            if metadata is not None:
                svg.remove(metadata)
            # Get rid of empty defs
            defs = svg.find('defs')
            if defs is not None and len(defs) == 0:
                svg.remove(defs)
            # Undo global page coordinate transforms
            units_in_pt = unwrap_transforms(svg)
            # Plug in actual size data
            if page_extents['display']:
                scale = 72/96 if units_in_pt else 1
                svg.attrib['viewBox'] = '{} {} {} {}'.format(
                    smart_float(scale * page_extents['left']),
                    smart_float(scale * page_extents['top']),
                    smart_float(scale * page_extents['width']),
                    smart_float(scale * page_extents['height'])
                )
                # The height is 1em.  The fonts in the pdf file are relative to
                # fontsize.
                svg.attrib['height'] = '{}em'.format(
                    smart_float(page_extents['heightem']))
            else:
                scale = 1 if units_in_pt else 96/72
                # The size of the view box doesn't matter, since the wrapper and
                # the strut take care of spacing.  Set it to a 1em square.
                svg.attrib['viewBox'] = '0 -{fs} {fs} {fs}'.format(
                    fs=smart_float(page_extents['fontsize']*(
                        1 if units_in_pt else 96/72)))
                # height is 1em; it is set in css
                del svg.attrib['height']
            # Get rid of ids
            for elt in svg.xpath('//*[@id]'):
                if not elt.xpath("ancestor::defs"):
                    del elt.attrib['id']
            # Clean up text styles
            for tspan in svg.xpath('//tspan[@style]'):
                self.process_tspan(tspan, page_extents['fontsize'])
            # Clean up path styles
            for path in svg.xpath('//path[@style]'):
                self.process_path(path)
            # Process linked images
            for img in svg.xpath('//image'):
                self.process_image(img)
            # Delete empty groups (recursively)
            todelete = svg.xpath('//g[count(*)=0]')
            while todelete:
                todelete2 = list(todelete)
                todelete = []
                for elt in todelete2:
                    parent = elt.getparent()
                    parent.remove(elt)
                    if parent.tag == 'g' and len(parent) == 0:
                        todelete.append(parent)
            if page_extents['display']:
                # Wrap displayed equations
                div = html.Element('div', {'class' : 'pretex-display'})
                div.append(svg)
                svg = div
                # Add tags
                for contents, pos in page_extents['tags']:
                    tagelt = html.Element('span', {'class' : 'tag'})
                    tagelt.text = '('+contents+')'
                    # This moves the tag down the calculated amount
                    htelt = html.Element('span', style='height:{}em'.format(
                        smart_float(pos / page_extents['fontsize'])))
                    tagelt.append(htelt)
                    svg.append(tagelt)
            else:
                # After much experimentation, this seems to be the most reliable
                # way to lock the origin of the svg to the baseline.
                wrapper = html.Element('span', {
                    'class' : 'pretex-inline',
                    'style' : 'width:{}em'.format(
                        smart_float(page_extents['widthem'])),
                })
                # make strut
                style = 'height:{}em'.format(
                    smart_float(page_extents['heightem'] +
                                page_extents['depthem']))
                if page_extents['depthem'] > 0.0:
                    style += ';vertical-align:-{}em'.format(
                        smart_float(page_extents['depthem']))
                wrapper.append(html.Element('span', style=style))
                # This last span is relatively positioned.  Its size will be
                # 0x0, so it sits right on the baseline.  The bottom of the svg
                # is then absolutely positioned to that.
                elt = html.Element('span')
                wrapper.append(elt)
                elt.append(svg)
                svg = wrapper
            svgs.append(svg)
        return svgs

    def process_tspan(self, tspan, page_font_size):
        "Simplify <tspan> tag."
        css = css_to_dict(tspan.attrib.get('style', ''))
        # These are hard-coded into the font, but not marked as such
        css.pop('font-variant', 1)
        css.pop('font-weight', 1)
        css.pop('font-style', 1)
        css.pop('-inkscape-font-specification', 1)
        # Get rid of inherited styles
        for key in self.DEFAULT_TEXT:
            if key in css and css[key] == self.DEFAULT_TEXT[key]:
                del css[key]
        # Add classes to save space
        classes = []
        if 'class' in tspan.attrib:
            classes = tspan.attrib['class'].split(' ')
        if 'font-size' in css:
            match = re.match(r'([\d\.]+).*', css['font-size'])
            size = float(match.group(1))
            if abs(size - page_font_size) <= .001:
                # It's using the default font size
                del css['font-size']
            else:
                classes.append(self.tspan_classes.get(
                    'font-size:'+css['font-size']))
                del css['font-size']
        # Replace font-family with a class (save space)
        if 'font-family' in css:
            font_family = css['font-family'].split(',')
            if font_family and font_family[0]:
                font_family = font_family[0]
                if font_family in self.font_hashes:
                    classes.append(self.font_hashes[font_family])
                else:
                    classes.append(self.tspan_classes.get(
                        'font-family:'+font_family))
                del css['font-family']
        tspan.attrib['style'] = dict_to_css(css)
        if not tspan.attrib['style']:
            del tspan.attrib['style']
        if classes:
            tspan.attrib['class'] = ' '.join(classes)

    def process_path(self, path):
        "Simplify <path> tag."
        css = css_to_dict(path.attrib.get('style', ''))
        # Get rid of inherited styles
        for key in self.DEFAULT_PATH:
            if key in css and css[key] == self.DEFAULT_PATH[key]:
                del css[key]
        if css.get('fill') == '#000000':
            css['fill'] = '#000'
        # Add classes to save space
        classes = []
        if 'class' in path.attrib:
            classes = path.attrib['class'].split(' ')
        if 'stroke-width' in css:
            classes.append(self.path_classes.get(
                'stroke-width:'+css['stroke-width']))
            del css['stroke-width']
        path.attrib['style'] = dict_to_css(css)
        if not path.attrib['style']:
            del path.attrib['style']
        if classes:
            path.attrib['class'] = ' '.join(classes)

    def process_image(self, img):
        "Simplify <image> tag."
        href = img.attrib['xlink:href']
        del img.attrib['xlink:href']
        # Inkscape has no idea where the file ended up
        fname = os.path.join(self.out_img_dir, os.path.basename(href))
        # Cache the image by a hash of its content
        with open(fname, 'rb') as fobj:
            img_hash = b64_hash(fobj.read())
        img_name = img_hash + '.png'
        self.images.append(img_name)
        img.attrib['href'] = FIGURE_IMG_DIR + '/' + img_name
        # Move to the cache directory
        move(fname, os.path.join(self.cache_dir, img_name))
        # Simplify css
        css = css_to_dict(img.get('style', ''))
        css.pop('image-rendering', 1)
        img.attrib['style'] = dict_to_css(css)
        if not img.attrib['style']:
            del img.attrib['style']


def almost_zero(num, ε=0.0001):
    return abs(num) < ε

def smart_round(num, decimals=8):
    'Round "num" to the fewest decimal places possible within given precision'
    # There must be a less stupid algorithm...
    if not isinstance(num, float):
        return num
    error = 1.0
    for i in range(decimals):
        error /= 10
    if num < 0:
        num *= -1
        neg = -1
    else:
        neg = 1
    for i in range(decimals):
        shift = num
        for j in range(i):
            shift *= 10
        approx1 = int(shift)
        approx2 = int(shift) + 1
        for j in range(i):
            approx1 /= 10.0
            approx2 /= 10.0
        if num - approx1 < error:
            return format(neg * approx1, "." + str(i) + "f")
        if approx2 - num < error:
            return format(neg * approx2, "." + str(i) + "f")
    return neg * num

def simplify_transforms(svg):
    'Re-format transform attributes to save characters.'
    for elt in svg.xpath('//*[@transform]'):
        mat = simpletransform.parse_transform(elt.attrib['transform'])
        # Recognize identity / translation
        if (almost_zero(mat[0][0] - 1) and
            almost_zero(mat[1][1] - 1) and
            almost_zero(mat[0][1]) and
            almost_zero(mat[1][0])):
            if almost_zero(mat[1][2]):
                if almost_zero(mat[0][2]):
                    del elt.attrib['transform']
                    continue
                elt.attrib['transform'] = 'translate({})'.format(
                    smart_round(mat[0][2]))
                continue
            elt.attrib['transform'] = 'translate({} {})'.format(
                smart_round(mat[0][2]), smart_round(mat[1][2]))
            continue
        # Recognize scale
        if (almost_zero(mat[0][1]) and
            almost_zero(mat[0][2]) and
            almost_zero(mat[1][0]) and
            almost_zero(mat[1][2])):
            if almost_zero(mat[0][0] - mat[1][1]):
                elt.attrib['transform'] = 'scale({})'.format(
                    smart_round(mat[0][0]))
                continue
            elt.attrib['transform'] = 'scale({} {})'.format(
                smart_round(mat[0][0]), smart_round(mat[1][1]))
            continue
        elt.attrib['transform'] = "matrix({},{},{},{},{},{})".format(
            smart_round(mat[0][0]), smart_round(mat[1][0]),
            smart_round(mat[0][1]), smart_round(mat[1][1]),
            smart_round(mat[0][2]), smart_round(mat[1][2]))

def unwrap_transforms(svg):
    'Undo global coordinate transformation, if there is one.'
    groups = svg.findall('g')
    if len(groups) != 1:
        return False
    group = groups[0]
    if not set(group.attrib.keys()) <= {'id', 'transform'}:
        return False
    if not group.attrib.get('transform'):
        return False
    mat = simpletransform.parse_transform(group.attrib['transform'])
    # Recognize pdf coordinate transformation
    if not (almost_zero(mat[0][0] - 4/3) and
            almost_zero(mat[1][1] + 4/3) and
            almost_zero(mat[0][1])       and
            almost_zero(mat[1][0])       and
            almost_zero(mat[0][2])):
        return False
    mat = [[1, 0, 0], [0, -1, mat[1][2]*3/4]]
    for child in group:
        child_mat = simpletransform.parse_transform(
            child.attrib.get('transform', ''), mat)
        child.attrib['transform'] = simpletransform.format_transform(child_mat)
        svg.append(child)
    svg.remove(group)
    simplify_transforms(svg)
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Process LaTeX in html files.')
    parser.add_argument('--preamble', default='preamble.tex', type=str,
                        help='LaTeX preamble')
    parser.add_argument('--style-path', default='', type=str,
                        help='Location of LaTeX style files')
    parser.add_argument('--cache-dir', default='pretex-cache', type=str,
                        help='Cache directory')
    parser.add_argument('--img-dir', default='figure-images', type=str,
                        help='LaTeX image include directory')
    parser.add_argument('--no-cache', action='store_true',
                        help='Ignore cache and regenerate')
    parser.add_argument('htmls', type=str, nargs='+',
                        help='HTML files to process')
    args = parser.parse_args()

    with open(args.preamble) as fobj:
        preamble = fobj.read()

    if args.style_path:
        os.environ['TEXINPUTS'] = '.:{}:'.format(args.style_path)
    os.makedirs(args.cache_dir, exist_ok=True)

    with TemporaryDirectory() as tmpdir:
    #tmpdir = os.path.realpath('./tmp')
    #if True:
        html_files = [HTMLDoc(html, preamble, tmpdir,
                              args.cache_dir, args.img_dir)
                      for html in args.htmls]

        # Create pdf files
        log("Processing {} files".format(len(html_files)))
        log("Extracting code and running LaTeX...")
        done = set()
        for html in html_files:
            if not html.make_latex():
                # Nothing to TeX
                done.add(html)
                continue
            if html.is_cached and not args.no_cache:
                html.use_cached(html.html_file)
                done.add(html)
                continue
            else:
                log("(Re)processing {}".format(
                    os.path.basename(html.html_file)))
                html.latex()
        html_files = [h for h in html_files if h not in done]
        if not html_files:
            log("Done!")
            return
        pdf_files = [html.pdf_file for html in html_files]
        html_byhash = {html.basename : html for html in html_files}

        log("Adding unicode codepoints to fonts...")
        # Add unicode codepoints to fonts in all pdf files
        sfd_dir = os.path.join(tmpdir, 'sfd')
        os.makedirs(sfd_dir, exist_ok=True)
        proc = Popen(['python2', TOUNICODE, '--outdir', sfd_dir] + pdf_files,
                     stdout=PIPE, stderr=PIPE)
        check_proc(proc, 'Could not add unicode codepoints to fonts')
        # Now the extents are known; read in the pages
        for html in html_files:
            html.read_extents()

        # Convert all fonts
        log("Converting fonts to woff format...")
        woff_dir = os.path.join(tmpdir, 'woff')
        os.makedirs(woff_dir, exist_ok=True)
        script = []
        for fname in os.listdir(sfd_dir):
            if fname[-4:] != '.sfd':
                continue
            fullpath = os.path.join(sfd_dir, fname)
            entry = ''
            entry += 'Open("{}")\n'.format(fullpath)
            entry += FIX_PRIVATE_TABLE
            entry += 'Generate("{}")\n'.format(
                os.path.join(woff_dir, fname[:-4] + '.woff'))
            script.append(entry)
            # Process 1000 at a time; otherwise ff might segfault
            if len(script) == 1000:
                proc = Popen([FONTFORGE, '-lang=ff', '-script', '-'],
                             stdin=PIPE, stdout=PIPE, stderr=PIPE)
                check_proc(proc, 'Could not convert pdf fonts to woff format',
                           stdin=''.join(script))
                script = []
        proc = Popen([FONTFORGE, '-lang=ff', '-script', '-'],
                     stdin=PIPE, stdout=PIPE, stderr=PIPE)
        check_proc(proc, 'Could not convert pdf fonts to woff format',
                   stdin=''.join(script))

        # Associate the fonts with their html filse
        for fname in os.listdir(woff_dir):
            match = re.match(r'\[(.*)\](.*)\.woff', fname)
            if not match:
                continue
            hash_name, font_name = match.groups()
            html_byhash[hash_name].add_font(
                font_name.replace('+', ' '), os.path.join(woff_dir, fname))

        # Convert all pages of all pdf files to svg files
        log("Generating svg files...")
        # inkscape exports images to the current directory
        img_dir = os.path.join(tmpdir, 'img')
        os.makedirs(img_dir, exist_ok=True)
        script = ''.join(html.inkscape_script() for html in html_files)
        proc = Popen(['inkscape', '--shell'],
                     stdout=PIPE, stderr=PIPE, stdin=PIPE,
                     cwd=img_dir)
        check_proc(proc, "SVG conversion failed", script)

        # Process svg files and write html
        log("Writing html files...")
        for html in html_files:
            html.write_html(html.html_file)
        log("Done!")


if __name__ == "__main__":
    main()
