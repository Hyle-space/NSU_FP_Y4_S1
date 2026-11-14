"""Build HTML fragments for the public LaTeX lessons listed in structure.json."""
import json
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / 'site/web/search-index/structure.json'
PICTURE = re.compile(r'\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}', re.S)
SETUP = re.compile(r'\\(?:tikzset|pgfplotsset|pgfmathdeclarefunction\{[^{}]+\}\{[^{}]+\})\s*(?=\{)')
COMMENT = re.compile(r'(?m)(?<!\\)%[^\n]*')
GROUP = r'\{(?:[^{}]|\{[^{}]*\})*\}'
COMMANDS = r'''
\newcommand{\rconcept}[1]{\textbf{#1}}
\newcommand{\rresult}[1]{\textbf{#1}}
\newcommand{\rassumption}[1]{\emph{#1}}
\newcommand{\rnote}[1]{\emph{#1}}
\newcommand{\rterm}[1]{\textbf{#1}}
\newcommand{\rsubtitle}[1]{\emph{#1}}
\newcommand{\texorpdfstring}[2]{#1}
\newcommand{\rcenter}[1]{#1}
\newcommand{\rtxt}[2]{#2}
\newcommand{\ruline}[2]{#2}
\newcommand{\rtag}[2]{#2}
\newcommand{\rhl}[2]{#2}
\newcommand{\ifSubfilesClassLoaded}[2]{#2}
\newcommand{\captionsetup}[1]{}
\newcommand{\Needspace}[1]{}
\newcommand{\practice}[3]{\chapter{#3}}
\newcommand{\rtheory}[1]{\section*{#1}}
\newcommand{\rtitle}[1]{\section*{#1}}
\newcommand{\condition}{\par\textbf{Условие}\par}
\newcommand{\solution}{\par\textbf{Решение}\par}
\newcommand{\answer}{\par\textbf{Ответ}\par}
\newcommand{\remark}[1][Замечание.]{\par\textbf{#1}\par}
\newcommand{\captionof}[2]{\par\emph{#2}\par}
'''
TIKZ_PREAMBLE = r'''
\documentclass[tikz,border=5pt]{standalone}
\usepackage{fontspec,amsmath,amssymb,braket,bm,pgfplots,tkz-euclide,tikz-3dplot}
\usepackage{unicode-math}
\setmainfont{DejaVu Serif}
\setmathfont{Latin Modern Math}
\renewcommand{\boldsymbol}[1]{\symbf{#1}}
\renewcommand{\bm}[1]{\symbf{#1}}
\newcommand{\subfix}[1]{parts/#1}
\pgfplotsset{compat=1.18}
\usetikzlibrary{arrows.meta,3d,backgrounds,intersections,calc,patterns,angles,quotes,
decorations.markings,bending,decorations.pathmorphing,perspective,shadings,shapes.arrows}
\usepgfplotslibrary{colormaps,patchplots,fillbetween,groupplots}
\input{style/colors}
\color{rtext}
'''


def run(args, cwd, text=None):
    process = subprocess.run(args, cwd=cwd, input=text, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError(f'{args[0]}: {process.stdout[-3500:]}')
    return process.stdout


def tikz_setups(text):
    """Return graphic style declarations, respecting nested braces."""
    for match in SETUP.finditer(text):
        level = 0
        for i in range(match.end(), len(text)):
            if text[i] == '{':
                level += 1
            elif text[i] == '}':
                level -= 1
                if level == 0:
                    yield text[match.start():i + 1]
                    break


def add_equation_anchor(match):
    tex = match[2]
    label = re.search(r'\\label\{([\w:.-]+)\}', tex)
    number = re.search(r'\\tag\{([\d.]+)\}', tex)
    if not label:
        return match[0]
    data = f' id="{label[1]}"'
    if number:
        data += f' data-equation="{number[1]}"'
    tex = tex[:label.start()] + tex[label.end():]
    return match[1][:-1] + data + '>' + tex + match[3]


def lesson(out, group, item):
    source = ROOT / item['source']
    base = source.parent.parent
    key = f"{group['subject']}/{group['section']}/{item['number']}"
    dest = out / key
    dest.mkdir(parents=True, exist_ok=True)
    text = COMMENT.sub('', source.read_text(encoding='utf-8'))
    body = text.split(r'\begin{document}', 1)[1].rsplit(r'\end{document}', 1)[0]
    pictures = list(PICTURE.finditer(body))
    diagrams = {}
    with tempfile.TemporaryDirectory() as tmp:
        temp = Path(tmp)
        if pictures:
            # Render the existing diagrams separately. The lesson text and equations stay HTML.
            tex = temp / 'diagrams.tex'
            setup = '\n'.join(dict.fromkeys(tikz_setups(text)))
            tex.write_text(TIKZ_PREAMBLE + r'\begin{document}' + '\n' + setup + '\n'
                           + '\n'.join(re.sub(r'\n\s*\n', '\n', p.group()) for p in pictures)
                           + '\n' + r'\end{document}', encoding='utf-8')
            run(['xelatex', '-no-shell-escape', '-halt-on-error', '-interaction=nonstopmode',
                 '-output-directory=' + tmp, str(tex)], base)
            pdf = temp / 'diagrams.pdf'
            pages = re.search(r'^Pages:\s+(\d+)', run(['pdfinfo', str(pdf)], base), re.M)
            if not pages or int(pages[1]) != len(pictures):
                raise RuntimeError(f'{source}: unexpected PDF page count for {len(pictures)} diagrams')
            for n, picture in reversed(list(enumerate(pictures, 1))):
                file = temp / f'diagram-{n}.svg'
                run(['pdftocairo', '-f', str(n), '-l', str(n), '-svg', str(pdf), str(file)], base)
                svg = file.read_text(encoding='utf-8')
                svg = svg[svg.index('<svg'):]
                prefix = f'diagram-{item["number"]}-{n}-'
                svg = re.sub(r'(id="|href="#|url\(#)([\w.-]+)', lambda m: m[1] + prefix + m[2], svg)
                svg = svg.replace('<svg ', '<svg role="img" aria-label="Схема из конспекта" ', 1)
                placeholder = f'HYLETIKZFIGURE{n}END'
                diagrams[placeholder] = svg
                body = body[:picture.start()] + '\n\n' + placeholder + '\n\n' + body[picture.end():]

        for setup in reversed(list(tikz_setups(body))):
            body = body.replace(setup, '', 1)

        def asset(match):
            name = match[1]
            path = (base / name).resolve()
            if path.is_relative_to(base) and path.is_file():
                output = dest / path.name
                shutil.copyfile(path, output)
                name = path.name
            elif not (dest / name).is_file():
                raise RuntimeError(f'{source}: missing image {name}')
            return r'\includegraphics{' + name + '}'

        body = re.sub(r'\\includegraphics(?:\s*\[[^\]]*\])?\s*\{([^{}]+)\}', asset, body)
        body = re.sub(r'\\begin\{r(?:box|fig|formula)\}(?:\s*\[[^\]]*\])?\s*'
                      + GROUP + r'(?:\s*\{\})?', '\n\n', body)
        body = re.sub(r'\\end\{r(?:box|fig|formula)\}', '\n\n', body)
        body = body.replace(r'\rboxed', r'\boxed')
        equation_number = 0

        def equation(match):
            nonlocal equation_number
            equation_number += 1
            return r'\begin{equation}' + match[1] + r'\tag{' + f"{item['number']}.{equation_number}" + r'}\end{equation}'

        body = re.sub(r'\\begin\{equation\}(.*?)\\end\{equation\}', equation, body, flags=re.S)
        task_number = 0

        def task(match):
            nonlocal task_number
            task_number = int(match[1]) if match[1] else task_number + 1
            return r'\section*{Задача ' + str(task_number) + '. ' + match[2][1:]

        body = re.sub(r'\\task(?:\[(\d+)\])?\s*(' + GROUP + ')', task, body)
        output = temp / 'lesson.html'
        document = COMMANDS + '\n' + r'\begin{document}' + body + r'\end{document}'
        run(['pandoc', '--from=latex', '--to=html5', '--mathjax', '--output=' + str(output)],
            base, document)
        fragment = output.read_text(encoding='utf-8')
        if not fragment.strip() or not re.search(r'<h[1-4]\b', fragment):
            raise RuntimeError(f'{source}: missing lesson heading')
        fragment = re.sub(
            r'(<span\s+class="math display">)(.*?)(</span>)',
            add_equation_anchor, fragment, flags=re.S
        )
        for placeholder, svg in diagrams.items():
            if fragment.count(placeholder) != 1:
                raise RuntimeError(f'{source}: diagram placeholder {placeholder} missing')
            fragment = fragment.replace(placeholder, '<span class="course-vector">' + svg + '</span>')
        # Give the reader an anchor even when Pandoc does not attach a label to its heading.
        (dest / 'index.html').write_text(fragment, encoding='utf-8')
    labels = {}
    for match in re.finditer(r'<(?:h[1-4]|span)\b[^>]*\bid="([\w:.-]+)"[^>]*>(.*?)</(?:h[1-4]|span)>', fragment, re.S):
        label, value = match.groups()
        if ':' in label and re.match(r'^[a-z]+:', label):
            number = re.search(r'data-equation="([\d.]+)"', match[0].split('>', 1)[0])
            labels[label] = '(' + number[1] + ')' if number else re.sub(r'<[^>]+>', '', value).strip()
    return item['id'], {'path': quote(key + '/index.html'), 'labels': labels}


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = [
        (group, item)
        for group in json.loads(INDEX.read_text(encoding='utf-8'))['groups']
        for item in group['items']
        if '/LaTeX/parts/' in item.get('source', '')
        and (ROOT / item['source']).is_file()
    ]
    failures = []
    manifest = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        pending = [(item, executor.submit(lesson, out, group, item)) for group, item in jobs]
        for item, future in pending:
            try:
                key, url = future.result()
                manifest[key] = url
            except (RuntimeError, IndexError) as error:
                failures.append(item['id'])
                print(f"HTML fallback for {item['id']}: {error}", flush=True)
    if not manifest:
        raise RuntimeError('No HTML lessons built')
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    print(f'HTML reader: {len(manifest)} lessons, {len(failures)} use PDF fallback')


if __name__ == '__main__':
    import sys
    main(sys.argv[1])
