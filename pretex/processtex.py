#!env python3

import argparse
import json
import logging
import os
import re
import sys
from base64 import b64encode
from hashlib import md5
from subprocess import Popen, PIPE
from tempfile import TemporaryDirectory

import cssutils
from bs4 import BeautifulSoup

import simpletransform

cssutils.log.setLevel(logging.CRITICAL)

BASE = os.path.dirname(__file__)
TOUNICODE = os.path.join(BASE, 'tounicode.py')

import platform
if platform.system() == 'Darwin':
    FONTFORGE = '/Applications/FontForge.app/Contents/Resources/opt/local/bin/fontforge'
else:
    FONTFORGE = 'fontforge'


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


class HTMLDoc:
    """
    Stores all data needed to convert the LaTeX in an html file.
    """

    SVG_ATTRS = set(['viewBox', 'height', 'width', 'version'])

    DEFAULT_TEXT = cssutils.parseStyle('''
        writing-mode: lr-tb;
        fill:         #000;
        fill-opacity: 1;
        fill-rule:    nonzero;
        stroke:       none;
    ''')
    DEFAULT_PATH = cssutils.parseStyle('''
        fill:              none;
        stroke:            #000;
        stroke-linecap:    butt;
        stroke-linejoin:   miter;
        stroke-miterlimit: 10;
        stroke-dasharray:  none;
        stroke-opacity:    1;
    ''')

    def __init__(self, html_file, preamble, tmp_dir, cache_dir):
        self.html_file = html_file
        with open(self.html_file) as fobj:
            self.html_data = fobj.read()
        self.dom = BeautifulSoup(self.html_data, 'lxml')
        self.to_replace = []
        self.preamble = preamble
        self.basename = md5(self.html_data.encode()).hexdigest()
        self.base_dir = os.path.join(tmp_dir, self.basename)
        self.pdf_dir = os.path.join(self.base_dir, 'pdf')
        self.svg_dir = os.path.join(self.base_dir, 'svg')
        self.cache_dir = cache_dir

        os.makedirs(self.base_dir, exist_ok=True)
        os.makedirs(self.pdf_dir, exist_ok=True)
        os.makedirs(self.svg_dir, exist_ok=True)

        self.latex_file = os.path.join(self.pdf_dir, self.basename + '.tex')
        self.pdf_file = os.path.join(self.pdf_dir, self.basename + '.pdf')
        self.boxsize_file = os.path.join(self.pdf_dir, 'boxsize.txt')
        self.pages_extents = []
        self.num_pages = 0
        self.fonts = {}
        self.font_hashes = {}
        self.html_cache = None

    @property
    def is_cached(self):
        return os.path.exists(self.html_cache)

    def svg_file(self, num):
        return os.path.join(self.svg_dir, 'out{:03d}.svg'.format(num+1))

    def make_latex(self):
        "Extract math from the html file, then make a LaTeX file."
        self.to_replace = []
        pages = []
        for elt in self.dom.find_all(
                'script', type=re.compile('text/x-latex-.*')):
            if not elt.string:
                continue
            code = elt.string.strip()
            if elt['type'] == 'text/x-latex-inline':
                pages.append(LATEX_INLINE.format(code=code))
                pages.append(LATEX_NEWPAGE)
            if elt['type'] == 'text/x-latex-code-inline':
                pages.append(LATEX_CODE_INLINE.format(code=code))
                pages.append(LATEX_NEWPAGE)
            elif elt['type'] in ('text/x-latex-display', 'text/x-latex-code'):
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
            contents += LATEX_NEWPAGE.join(pages)
            contents += r'\end{document}'
        # Now we know the hash file name
        self.html_cache = os.path.join(
            self.cache_dir, md5(contents.encode()).hexdigest())
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
        self.font_hashes[name] = 'f'+md5(self.fonts[name]).hexdigest()[:4]

    def write_cache(self, style, fonts, svgs):
        "Cache the computed data"
        cache = {
            'svgs'  : svgs,
            'style' : style,
            'fonts' : fonts,
        }
        with open(self.html_cache, 'w') as fobj:
            json.dump(cache, fobj)

    def use_cached(self, outfile):
        "Write the cached output to the html file."
        with open(self.html_cache) as fobj:
            cache = json.load(fobj)
        # Replace DOM elements
        for i, elt in enumerate(self.to_replace):
            root = BeautifulSoup(cache['svgs'][i], 'lxml')
            root.html.unwrap()
            root.body.unwrap()
            elt.replace_with(root)
        style_elt = self.dom.find(id='pretex-style')
        if style_elt is not None:
            style_elt.string = cache['style']
        style_elt = self.dom.find(id='pretex-fonts')
        if style_elt is not None:
            style_elt.string = cache['fonts']
        with open(outfile, 'w') as outf:
            outf.write(str(self.dom))

    def write_html(self, outfile):
        svgs = self.process_svgs()
        cached_elts = []
        # Replace DOM elements
        for i, elt in enumerate(self.to_replace):
            elt_str = str(svgs[i])
            elt.replace_with(svgs[i])
            cached_elts.append(elt_str)
        style = PRETEX_STYLE
        style += r'''
        svg.pretex text {{
          {}
        }}
        svg.pretex path {{
          {}
        }}
        '''.format(self.DEFAULT_TEXT.cssText, self.DEFAULT_PATH.cssText)
        style_elt = self.dom.find(id='pretex-style')
        if style_elt is not None:
            style_elt.string = style
        # Add fonts
        font_style = ''
        for name, data in self.fonts.items():
            name = self.font_hashes[name]
            font_style += r'''
            @font-face {{
              font-family: "{name}";
              src: url(data:application/font-woff;base64,{data}) format('woff');
            }}
            '''.format(name=name, data=b64encode(data).decode('ascii'))
        style_elt = self.dom.find(id='pretex-fonts')
        if style_elt is not None:
            style_elt.string = font_style
        with open(outfile, 'w') as outf:
            outf.write(str(self.dom))
        self.write_cache(style, font_style, cached_elts)

    def process_svgs(self):
        "Process all generated svgs file for use in an html page."
        svgs = []
        for page_num, page_extents in enumerate(self.pages_extents):
            with open(self.svg_file(page_num)) as fobj:
                # If bs4 sees a namespace it generates prefixed tags
                lines = [line for line in fobj if line.find('xmlns=') == -1]
                soup = BeautifulSoup(''.join(lines), 'lxml')
            elt = soup.svg
            # Remove extra attrs from <svg>
            for key in list(elt.attrs.keys()):
                if key not in self.SVG_ATTRS:
                    del elt[key]
            # Auto-calculated based on height and viewBox aspect ratio
            del elt['width']
            elt['class'] = 'pretex'
            # Get rid of metadata
            try:
                elt.metadata.decompose()
            except AttributeError:
                pass
            # Get rid of empty defs
            if not elt.defs.find_all():
                elt.defs.decompose()
            # Undo global page coordinate transforms
            units_in_pt = unwrap_transforms(elt)
            # Plug in actual size data
            if page_extents['display']:
                scale = 72/96 if units_in_pt else 1
                elt['viewBox'] = '{} {} {} {}'.format(
                    scale * page_extents['left'],
                    scale * page_extents['top'],
                    scale * page_extents['width'],
                    scale * page_extents['height']
                )
                # The height is 1em.  The fonts in the pdf file are relative to
                # fontsize.
                elt['height'] = '{}em'.format(page_extents['heightem'])
            else:
                scale = 1 if units_in_pt else 96/72
                # The size of the view box doesn't matter, since the wrapper and
                # the strut take care of spacing.  Set it to a 1em square.
                elt['viewBox'] = '0 -{fs} {fs} {fs}'.format(
                    fs=page_extents['fontsize']*(
                        1 if units_in_pt else 96/72))
                # height is 1em; it is set in css
                del elt['height']
            # Clean up text styles
            for tspan in elt.find_all('tspan', style=True):
                css = cssutils.parseStyle(tspan['style'])
                # These are hard-coded into the font, but not marked as such
                del css['font-variant']
                del css['font-weight']
                del css['font-style']
                del css['-inkscape-font-specification']
                # Get rid of inherited styles
                for key in self.DEFAULT_TEXT.keys():
                    if css[key] == self.DEFAULT_TEXT[key]:
                        del css[key]
                if 'font-size' in css:
                    match = re.match(r'([\d\.]+).*', css['font-size'])
                    size = float(match.group(1))
                    if abs(size - page_extents['fontsize']) <= .001:
                        # It's using the default font size
                        del css['font-size']
                # Replace font-family with font number (save space)
                font_family = css.getPropertyCSSValue('font-family')
                if font_family[0]:
                    font_family = font_family[0].value
                if font_family in self.font_hashes:
                    css['font-family'] = self.font_hashes[font_family]
                tspan['style'] = css.cssText
            # Clean up path styles
            for path in elt.find_all('path', style=True):
                css = cssutils.parseStyle(path['style'])
                # Get rid of inherited styles
                for key in self.DEFAULT_PATH.keys():
                    if css[key] == self.DEFAULT_PATH[key]:
                        del css[key]
                path['style'] = css.cssText
            # Get rid of ids
            for elt2 in elt.find_all(id=True):
                if not elt2.find_parents("defs"):
                    del elt2['id']
            if page_extents['display']:
                # Wrap displayed equations
                elt = elt.wrap(soup.new_tag('div'))
                elt['class'] = 'pretex-display'
                # Add tags
                for contents, pos in page_extents['tags']:
                    tagelt = soup.new_tag('span')
                    tagelt['class'] = 'tag'
                    tagelt.string = '('+contents+')'
                    # This moves the tag down the calculated amount
                    htelt = soup.new_tag('span')
                    htelt['style'] = 'height:{}em'.format(
                        pos / page_extents['fontsize'])
                    tagelt.append(htelt)
                    elt.append(tagelt)
            else:
                # After much experimentation, this seems to be the most reliable
                # way to lock the origin of the svg to the baseline.
                wrapper = soup.new_tag('span')
                wrapper['class'] = 'pretex-inline'
                wrapper['style'] = 'width:{}em'.format(page_extents['widthem'])
                elt.wrap(wrapper)
                # make strut
                style = 'height:{}em'.format(
                    page_extents['heightem'] + page_extents['depthem'])
                if page_extents['depthem'] > 0.0:
                    style += ';vertical-align:-{}em'.format(
                        page_extents['depthem'])
                elt.insert_before(soup.new_tag('span', style=style))
                # This last span is relatively positioned.  Its size will be
                # 0x0, so it sits right on the baseline.  The bottom of the svg
                # is then absolutely positioned to that.
                elt.wrap(soup.new_tag('span'))
                elt = wrapper
            svgs.append(elt)
        return svgs


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
            return ("{:." + str(i) + "f}").format(neg * approx1)
        if approx2 - num < error:
            return ("{:." + str(i) + "f}").format(neg * approx2)
    return neg * num

def simplify_transforms(svg):
    'Re-format transform attributes to save characters.'
    for elt in svg.find_all(transform=True):
        mat = simpletransform.parse_transform(elt['transform'])
        # Recognize identity / translation
        if (almost_zero(mat[0][0] - 1) and
            almost_zero(mat[1][1] - 1) and
            almost_zero(mat[0][1]) and
            almost_zero(mat[1][0])):
            if almost_zero(mat[1][2]):
                if almost_zero(mat[0][2]):
                    del elt['transform']
                    continue
                elt['transform'] = 'translate({})'.format(
                    smart_round(mat[0][2]))
                continue
            elt['transform'] = 'translate({} {})'.format(
                smart_round(mat[0][2]), smart_round(mat[1][2]))
            continue
        # Recognize scale
        if (almost_zero(mat[0][1]) and
            almost_zero(mat[0][2]) and
            almost_zero(mat[1][0]) and
            almost_zero(mat[1][2])):
            if almost_zero(mat[0][0] - mat[1][1]):
                elt['transform'] = 'scale({})'.format(
                    smart_round(mat[0][0]))
                continue
            elt['transform'] = 'scale({} {})'.format(
                smart_round(mat[0][0]), smart_round(mat[1][1]))
            continue
        elt['transform'] = "matrix({},{},{},{},{},{})".format(
            smart_round(mat[0][0]), smart_round(mat[1][0]),
            smart_round(mat[0][1]), smart_round(mat[1][1]),
            smart_round(mat[0][2]), smart_round(mat[1][2]))

def unwrap_transforms(svg):
    'Undo global coordinate transformation, if there is one.'
    groups = svg.find_all('g', recursive=False)
    if len(groups) != 1:
        return False
    group = groups[0]
    if not set(group.attrs.keys()) <= {'id', 'transform'}:
        return False
    if not group.get('transform'):
        return False
    mat = simpletransform.parse_transform(group['transform'])
    # Recognize pdf coordinate transformation
    if not (almost_zero(mat[0][0] - 4/3) and
            almost_zero(mat[1][1] + 4/3) and
            almost_zero(mat[0][1])       and
            almost_zero(mat[1][0])       and
            almost_zero(mat[0][2])):
        return False
    mat = [[1, 0, 0], [0, -1, mat[1][2]*3/4]]
    for child in group.find_all(recursive=False):
        child_mat = simpletransform.parse_transform(child.get('transform'), mat)
        child['transform'] = simpletransform.format_transform(child_mat)
    group.unwrap()
    simplify_transforms(svg)
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Process LaTeX in html files.')
    parser.add_argument('--preamble', default='preamble.tex', type=str,
                        help='LaTeX preamble')
    parser.add_argument('--style-path', default='', type=str,
                        help='Location of LaTeX style files')
    # parser.add_argument('--outdir', default='build', type=str,
    #                     help='Output processed files to this directory')
    parser.add_argument('--cache-dir', default='pretex-cache', type=str,
                        help='Cache directory')
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
    #tmpdir = 'tmp'
    #if True:
        html_files = [HTMLDoc(html, preamble, tmpdir, args.cache_dir)
                      for html in args.htmls]

        # Create pdf files
        print("Extracting code and running LaTeX...")
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
                print("(Re)processing {}".format(
                    os.path.basename(html.html_file)))
                html.latex()
        html_files = [h for h in html_files if h not in done]
        if not html_files:
            return
        pdf_files = [html.pdf_file for html in html_files]
        html_byhash = {html.basename : html for html in html_files}

        print("Adding unicode codepoints to fonts...")
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
        print("Converting fonts to woff format...")
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
        print("Generating svg files...")
        script = ''.join(html.inkscape_script() for html in html_files)
        proc = Popen(['inkscape', '--shell'],
                     stdout=PIPE, stderr=PIPE, stdin=PIPE)
        check_proc(proc, "SVG conversion failed", script)

        # Process svg files and write html
        print("Writing html files...")
        for html in html_files:
            html.write_html(html.html_file)


if __name__ == "__main__":
    main()
