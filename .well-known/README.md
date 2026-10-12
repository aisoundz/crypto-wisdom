# .well-known

`security.txt` lives here, at the path RFC 9116 specifies
(`/.well-known/security.txt`).

## Why `.nojekyll` exists in the repository root

GitHub Pages runs Jekyll over the repository by default, and Jekyll
**excludes every file and directory whose name begins with a dot or an
underscore** from the site it builds. Without the empty `.nojekyll` marker in
the root, this whole directory is silently dropped: the repository looks
correct, the Pages build reports success, and `/.well-known/security.txt`
returns 404.

That failure is invisible from the repository side, which is the only place
anyone usually looks. If `security.txt` ever starts 404ing, check that
`.nojekyll` is still in the root before anything else.
