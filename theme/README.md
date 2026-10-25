# Ghost appearance

Edit `src/` HTML, CSS and JavaScript. `header.txt` and `footer.txt` are generated
Ghost code-injection artifacts retained for compatibility and deployment review.

```sh
.venv/bin/python scripts/build_theme.py
.venv/bin/python scripts/build_theme.py --check
.venv/bin/python scripts/deploy_ghost_theme.py --apply
```

Deployment saves the previous injection in private `logs/theme-backups/` and
performs one homepage check. Restore with
`.venv/bin/python scripts/deploy_ghost_theme.py --rollback logs/theme-backups/FILE.json --apply`.
Never commit these backups or staff credentials. Ghost staff sessions require
`GHOST_ADMIN_EMAIL` and `GHOST_ADMIN_PASSWORD`; API integration keys cannot write
these settings. Provider authentication/device verification may block login.

The archive loader retains real Ghost pagination links, suppresses Casper's
parallel loader, and reveals a fallback link if automatic loading fails.
