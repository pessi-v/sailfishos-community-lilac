#!/usr/bin/env python3
"""Build and check a hybris-patches style patch series for one Android project, without a checkout.

The series for a project lives in SERIES/<project path>/NNNN-*.patch (git format-patch / mbox files,
the layout of mer-hybris/hybris-patches). Commits are made with a temporary index on top of the
project's HEAD (the pinned manifest revision), so no worktree is needed and the live tree is untouched.

  hp.py build  ROOT SERIES PROJECT [--upto N]  commit the series, print the tip commit (ref refs/lilac/hybris)
  hp.py rest   ROOT SERIES PROJECT [--upto N]  diff from the series tip to the live working tree (what the series lacks)
  hp.py verify ROOT SERIES PROJECT [--upto N]  exit 0 if the series tip tree equals the live working tree
  hp.py export ROOT PROJECT FROM TO OUTDIR     format-patch FROM..TO (commits made by hand on the lilac ref)
  hp.py mkpatch ROOT SERIES PROJECT SLUG MSGFILE PATH...
                                               write the next numbered patch: the rest (live - series tip) for
                                               PATH... with the subject/body of MSGFILE (first line = subject).
                                               Author: $HP_AUTHOR ("Name <mail>"); date: $HP_DATE or now.

ROOT is the Android tree (repo checkout). "Live working tree" = HEAD + every modification and every
untracked file that is not ignored, except *.orig/*.rej leftovers, which are listed separately.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

LEFTOVER = ('.orig', '.rej')
# Build products left inside source directories by hand builds; never part of a patch.
# More globs (relative to the project) can be given in $HP_IGNORE, separated by spaces.
IGNORE = ['**/*.o'] + os.environ.get('HP_IGNORE', '').split()


def git(proj, *args, env=None, input=None, check=True):
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run(['git', '-C', str(proj), *args], env=e, input=input,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed in {proj}:\n{r.stderr.decode(errors='replace')}")
    return r.stdout


def series_files(series, project, upto=None):
    """SERIES may be several roots separated by ':' (layers, applied in that order)."""
    files = []
    roots = series.split(':')
    for i, root in enumerate(roots):
        d = Path(root) / project
        layer = sorted(p for p in d.glob('*.patch')) if d.is_dir() else []
        if upto is not None and i == len(roots) - 1:
            layer = [p for p in layer if int(p.name[:4]) <= upto]
        files += layer
    return files


def mailinfo(patch):
    """Return (author, email, date, message, diff bytes) of an mbox patch."""
    with tempfile.TemporaryDirectory() as td:
        msg, pat = Path(td, 'msg'), Path(td, 'patch')
        with open(patch, 'rb') as f:
            r = subprocess.run(['git', 'mailinfo', '-k', str(msg), str(pat)], stdin=f,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r.returncode != 0:
            sys.exit(f'git mailinfo failed on {patch}: {r.stderr.decode()}')
        info = {}
        for line in r.stdout.decode(errors='replace').splitlines():
            k, _, v = line.partition(': ')
            info[k] = v
        body = msg.read_text(errors='replace').strip()
        message = info.get('Subject', '').strip() + ('\n\n' + body if body else '') + '\n'
        return info.get('Author', ''), info.get('Email', ''), info.get('Date', ''), message, pat.read_bytes()


_PINNED = None


def base_revision(proj, project):
    """The project's pinned manifest revision ($HP_MANIFEST, default ~/hp/manifest-pinned.xml); HEAD if not listed.
    The series is always built on that revision, so it does not matter where HEAD points now."""
    global _PINNED
    if _PINNED is None:
        import xml.etree.ElementTree as ET
        _PINNED = {}
        mf = Path(os.environ.get('HP_MANIFEST', os.path.expanduser('~/hp/manifest-pinned.xml')))
        if mf.exists():
            for e in ET.parse(mf).getroot().iter('project'):
                if e.get('revision'):
                    _PINNED[e.get('path') or e.get('name')] = e.get('revision')
    rev = _PINNED.get(project)
    return git(proj, 'rev-parse', (rev or 'HEAD') + '^{commit}').decode().strip()


def build(root, series, project, upto=None):
    proj = Path(root) / project
    tip = base_revision(proj, project)
    with tempfile.TemporaryDirectory() as td:
        env = {'GIT_INDEX_FILE': str(Path(td, 'index'))}
        git(proj, 'read-tree', tip, env=env)
        for p in series_files(series, project, upto):
            author, email, date, message, diff = mailinfo(p)
            if diff.strip():
                r = subprocess.run(['git', '-C', str(proj), 'apply', '--cached', '--whitespace=nowarn', '-'],
                                   env={**os.environ, **env}, input=diff,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if r.returncode != 0:
                    # context drifted: let git merge it three-way from the blobs named in the patch
                    r = subprocess.run(['git', '-C', str(proj), 'apply', '--cached', '-3', '--whitespace=nowarn', '-'],
                                       env={**os.environ, **env}, input=diff,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if r.returncode == 0:
                        print(f'# {p.name}: applied three-way', file=sys.stderr)
                if r.returncode != 0:
                    sys.exit(f'{p.name} does not apply on top of the previous patches:\n{r.stderr.decode()}')
            tree = git(proj, 'write-tree', env=env).decode().strip()
            cenv = {'GIT_AUTHOR_NAME': author, 'GIT_AUTHOR_EMAIL': email, 'GIT_AUTHOR_DATE': date,
                    'GIT_COMMITTER_NAME': author, 'GIT_COMMITTER_EMAIL': email, 'GIT_COMMITTER_DATE': date}
            tip = git(proj, 'commit-tree', tree, '-p', tip, env=cenv, input=message.encode()).decode().strip()
    git(proj, 'update-ref', 'refs/lilac/hybris', tip)
    return tip


def live_tree(proj):
    """Tree of the working directory as it is (tracked changes + untracked, minus leftovers)."""
    with tempfile.TemporaryDirectory() as td:
        env = {'GIT_INDEX_FILE': str(Path(td, 'index'))}
        git(proj, 'read-tree', 'HEAD', env=env)
        git(proj, 'add', '-A', '--', '.', *[f':(exclude,glob)**/*{s}' for s in LEFTOVER],
            *[f':(exclude,glob){g}' for g in IGNORE], env=env)
        return git(proj, 'write-tree', env=env).decode().strip()


def leftovers(proj):
    out = git(proj, 'status', '--porcelain', '--untracked-files=all').decode().splitlines()
    return [l[3:] for l in out if l.startswith('?? ') and l.endswith(LEFTOVER)]


def select_hunks(diff, regex, keep_matching):
    """Keep only the hunks whose text matches (or, keep_matching=False, does not match) regex."""
    import re
    rx = re.compile(regex.encode())
    out = []
    for fpart in re.split(rb'(?m)^(?=diff --git )', diff):
        if not fpart.strip():
            continue
        pieces = re.split(rb'(?m)^(?=@@ )', fpart)
        head, hunks = pieces[0], pieces[1:]
        kept = [h for h in hunks if bool(rx.search(h)) == keep_matching]
        if kept:
            out.append(head + b''.join(kept))
    return b''.join(out)


def main():
    a = sys.argv[1:]
    upto = None
    hunk_re, keep_matching = None, True
    for opt, keep in (('--hunks', True), ('--not-hunks', False)):
        if opt in a:
            i = a.index(opt)
            hunk_re, keep_matching = a[i + 1], keep
            del a[i:i + 2]
    if '--upto' in a:
        i = a.index('--upto')
        upto = int(a[i + 1])
        del a[i:i + 2]
    if not a:
        sys.exit(__doc__)
    cmd = a[0]
    if cmd in ('build', 'rest', 'verify'):
        root, series, project = a[1:4]
        proj = Path(root) / project
        tip = build(root, series, project, upto)
        if cmd == 'build':
            print(tip)
            return
        live = live_tree(proj)
        left = leftovers(proj)
        if left:
            print('# leftovers not compared: ' + ' '.join(left), file=sys.stderr)
        if cmd == 'rest':
            sys.stdout.buffer.write(git(proj, 'diff', '--binary', tip, live))
            return
        series_tree = git(proj, 'rev-parse', tip + '^{tree}').decode().strip()
        if series_tree == live:
            print(f'{project}: series reproduces the live tree ({len(series_files(series, project, upto))} patches)')
            return
        stat = git(proj, 'diff', '--stat', tip, live).decode()
        print(f'{project}: DIFFERS from the live tree\n{stat}')
        sys.exit(1)
    if cmd == 'mkpatch':
        root, series, project, slug, msgfile = a[1:6]
        paths = a[6:]
        if not paths:
            sys.exit('mkpatch needs at least one PATH')
        proj = Path(root) / project
        tip = build(root, series, project, upto)
        live = live_tree(proj)
        diff = git(proj, 'diff', '--binary', '--full-index', tip, live, '--', *paths)
        if hunk_re is not None:
            diff = select_hunks(diff, hunk_re, keep_matching)
        if not diff.strip():
            sys.exit('nothing left for those paths')
        lines = Path(msgfile).read_text().rstrip('\n').split('\n')
        subject, body = lines[0], '\n'.join(lines[1:]).strip('\n')
        stat = subprocess.run(['git', 'apply', '--stat', '-'], input=diff,
                              stdout=subprocess.PIPE).stdout.decode()
        author = os.environ.get('HP_AUTHOR', 'pessi-v <pessimo@posteo.net>')
        date = os.environ.get('HP_DATE') or subprocess.run(['date', '-R'], stdout=subprocess.PIPE).stdout.decode().strip()
        d = Path(series.split(':')[-1]) / project
        d.mkdir(parents=True, exist_ok=True)
        n = max([int(p.name[:4]) for p in d.glob('*.patch')] + [0]) + 1
        out = d / f'{n:04d}-{slug}.patch'
        text = (f'From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001\n'
                f'From: {author}\nDate: {date}\nSubject: [PATCH] {subject}\n\n'
                + (body + '\n' if body else '') + f'---\n{stat}\n')
        out.write_bytes(text.encode() + diff)
        print(out)
        return
    if cmd == 'newpatch':
        # newpatch ROOT SERIES PROJECT SLUG MSGFILE EDITPY: EDITPY defines FILES (paths) and edit(path, text)
        # -> new text; the change on top of the series tip becomes the next patch of the last layer.
        root, series, project, slug, msgfile, editpy = a[1:7]
        proj = Path(root) / project
        ns = {}
        exec(compile(Path(editpy).read_text(), editpy, 'exec'), ns)
        tip = build(root, series, project, upto)
        with tempfile.TemporaryDirectory() as td:
            env = {'GIT_INDEX_FILE': str(Path(td, 'index'))}
            git(proj, 'read-tree', tip, env=env)
            for path in ns['FILES']:
                text = git(proj, 'show', f'{tip}:{path}').decode()
                new = ns['edit'](path, text)
                if new == text:
                    sys.exit(f'edit() changed nothing in {path}')
                mode = git(proj, 'ls-files', '-s', '--', path, env=env).decode().split()[0]
                blob = git(proj, 'hash-object', '-w', '--stdin', input=new.encode()).decode().strip()
                git(proj, 'update-index', '--cacheinfo', f'{mode},{blob},{path}', env=env)
            after = git(proj, 'write-tree', env=env).decode().strip()
        diff = git(proj, 'diff', '--binary', '--full-index', tip, after)
        stat = subprocess.run(['git', 'apply', '--stat', '-'], input=diff, stdout=subprocess.PIPE).stdout.decode()
        lines = Path(msgfile).read_text().rstrip('\n').split('\n')
        subject, body = lines[0], '\n'.join(lines[1:]).strip('\n')
        author = os.environ.get('HP_AUTHOR', 'pessi-v <pessimo@posteo.net>')
        date = subprocess.run(['date', '-R'], stdout=subprocess.PIPE).stdout.decode().strip()
        d = Path(series.split(':')[-1]) / project
        d.mkdir(parents=True, exist_ok=True)
        n = max([int(p.name[:4]) for p in d.glob('*.patch')] + [0]) + 1
        out = d / f'{n:04d}-{slug}.patch'
        out.write_bytes((f'From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001\n'
                         f'From: {author}\nDate: {date}\nSubject: [PATCH] {subject}\n\n'
                         + (body + '\n' if body else '') + f'---\n{stat}\n').encode() + diff)
        print(out)
        return
    if cmd == 'reedit':
        # reedit ROOT SERIES PROJECT PATCHFILE EDITPY: rewrite the post-image of PATCHFILE's files with
        # EDITPY's edit(path, text) -> text, and regenerate the patch body (header and message kept).
        root, series, project, patchfile, editpy = a[1:6]
        proj = Path(root) / project
        patchfile = Path(patchfile)
        ns = {}
        exec(compile(Path(editpy).read_text(), editpy, 'exec'), ns)
        files = series_files(series, project)
        idx = [str(f) for f in files].index(str(patchfile))
        prev = files[:idx]
        tip = base_revision(proj, project)
        with tempfile.TemporaryDirectory() as td:
            env = {'GIT_INDEX_FILE': str(Path(td, 'index'))}
            git(proj, 'read-tree', tip, env=env)
            def apply(p):
                r = subprocess.run(['git', '-C', str(proj), 'apply', '--cached', '-3', '--whitespace=nowarn', '-'],
                                   env={**os.environ, **env}, input=mailinfo(p)[4],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if r.returncode != 0:
                    sys.exit(f'{p.name} does not apply:\n{r.stderr.decode()}')
            for p in prev:
                apply(p)
            before = git(proj, 'write-tree', env=env).decode().strip()
            apply(patchfile)
            changed = git(proj, 'diff', '--name-only', '--diff-filter=AM', before,
                          git(proj, 'write-tree', env=env).decode().strip()).decode().split()
            for path in changed:
                text = git(proj, 'cat-file', '-p', f':{path}', env=env).decode()
                new = ns['edit'](path, text)
                if new != text:
                    mode = git(proj, 'ls-files', '-s', '--', path, env=env).decode().split()[0]
                    blob = git(proj, 'hash-object', '-w', '--stdin', input=new.encode()).decode().strip()
                    git(proj, 'update-index', '--cacheinfo', f'{mode},{blob},{path}', env=env)
                    print(f'# edited {path}', file=sys.stderr)
            after = git(proj, 'write-tree', env=env).decode().strip()
        body = git(proj, 'diff', '--binary', '--full-index', before, after)
        stat = subprocess.run(['git', 'apply', '--stat', '-'], input=body, stdout=subprocess.PIPE).stdout.decode()
        text = patchfile.read_bytes()
        head = text.split(b'\n---\n', 1)[0]
        patchfile.write_bytes(head + b'\n---\n' + stat.encode() + b'\n' + body)
        print(patchfile)
        return
    if cmd == 'export':
        root, project, frm, to, outdir = a[1:6]
        git(Path(root) / project, 'format-patch', '--zero-commit', '--no-signature', '--full-index',
            '-o', outdir, f'{frm}..{to}')
        return
    sys.exit(__doc__)


if __name__ == '__main__':
    main()
