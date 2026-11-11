# Deploying Movie Club

This guide targets a single **Ubuntu 24.04 LTS** DigitalOcean Droplet running:

- A Nix-managed Python and application environment
- PostgreSQL 16 on the Droplet
- Gunicorn for the Django application
- systemd for process supervision
- Nginx as the reverse proxy and static-file server
- Let’s Encrypt for TLS

The application environment is declared by `flake.nix` and `uv.lock` and entered
with `nix/env` in both development and production. Nix does not manage the
Ubuntu host: PostgreSQL, Nginx, systemd, Certbot, and the firewall remain
Ubuntu-managed.

Replace every placeholder before running commands:

- `YOUR_DOMAIN`
- `SERVER_IP`
- `YOUR_REPOSITORY_URL`
- `LOCAL_DB_USER`
- `DB_PASSWORD`
- `BOT_API_TOKEN`
- `TMDB_READ_ACCESS_TOKEN`

The application lives at `/srv/movie-club`. SSH/deployments run as the `deploy`
user, while Gunicorn runs as the unprivileged `movieclub` user.

Never commit the database dump, `.env`, or production secrets to Git.

## 1. Create the Droplet and DNS

1. Create an Ubuntu 24.04 Droplet.
2. Add DNS `A` records for `YOUR_DOMAIN` and optionally
   `www.YOUR_DOMAIN` pointing to `SERVER_IP`.
3. Wait for DNS to resolve before requesting TLS.
4. SSH in as `root`, then create the deployment user:

```bash
adduser deploy
usermod -aG sudo deploy
```

Copy your public SSH key into `/home/deploy/.ssh/authorized_keys`, then confirm
that key-based login works before disabling password/root SSH access.

Install the application service user:

```bash
adduser --system --group --home /var/lib/movieclub --shell /usr/sbin/nologin movieclub
usermod -aG movieclub deploy
mkdir -p /srv/movie-club
chown deploy:movieclub /srv/movie-club
chmod 755 /srv/movie-club
```

Log out and back in as `deploy` so the new group membership applies.

## 2. Install system packages and Nix

The host services remain Ubuntu packages. Python, `uv`, and the application
dependencies come from the project’s Nix environment and `uv.lock`.

```bash
sudo apt update
sudo apt install -y \
  postgresql \
  postgresql-contrib \
  nginx \
  git \
  curl \
  xz-utils \
  ufw \
  certbot \
  python3-certbot-nginx
```

Install multi-user Nix as the `deploy` user:

```bash
sh <(curl -L https://nixos.org/nix/install) --daemon
```

Enable flakes, restart the daemon, then log out and back in so the Nix profile
is loaded:

```bash
sudo mkdir -p /etc/nix
echo 'experimental-features = nix-command flakes' | sudo tee -a /etc/nix/nix.conf
sudo systemctl restart nix-daemon

nix --version
psql --version
nginx -v
```

## 3. Configure PostgreSQL

Start PostgreSQL and create an application role and database:

```bash
sudo systemctl enable --now postgresql
sudo -u postgres psql
```

Inside `psql`:

```sql
CREATE ROLE movieclub LOGIN;
\password movieclub
CREATE DATABASE movieclub OWNER movieclub;
\q
```

Enter a strong password when prompted. Use the same password in the production
environment file and in `~/.pgpass` below.

Create a restricted password file for the `deploy` user:

```bash
read -rsp 'Database password: ' DB_PASSWORD; echo
printf '127.0.0.1:5432:movieclub:movieclub:%s\n' "$DB_PASSWORD" > ~/.pgpass
chmod 600 ~/.pgpass
unset DB_PASSWORD
```

PostgreSQL does not need to be exposed publicly. Keep port `5432` closed in
the firewall.

## 4. Deploy the application code

```bash
git clone YOUR_REPOSITORY_URL /srv/movie-club
cd /srv/movie-club
git checkout main
```

Make the code readable by the service user:

```bash
sudo chown -R deploy:movieclub /srv/movie-club
```

Install the pinned runtime profile into the `deploy` user’s Nix profile. This
roots the Nix Python and `uv` closure so garbage collection cannot remove the
interpreter used by the virtualenv:

```bash
cd /srv/movie-club
nix profile install .#runtime
```

Enter the same Nix environment used in development and install production
dependencies. This excludes the charting and test dependencies:

```bash
nix/env --command make sync-prod
sudo chmod -R g+rX,o+rX /srv/movie-club
```

The systemd service runs `/srv/movie-club/.venv/bin/gunicorn` directly and does
not invoke Nix at boot. The runtime profile is only needed to keep the Nix
closure alive.

## 5. Create the production environment file

```bash
sudo cp deploy/movieclub.env.example /etc/movieclub.env
sudo chown root:movieclub /etc/movieclub.env
sudo chmod 640 /etc/movieclub.env
sudoedit /etc/movieclub.env
```

Generate a production Django secret:

```bash
nix/env --command python3.12 -c 'import secrets; print(secrets.token_urlsafe(64))'
```

Replace every placeholder in `/etc/movieclub.env`. At minimum:

- Set `DJANGO_DEBUG=false`
- Set `DJANGO_ALLOWED_HOSTS` to your real hostname(s)
- Set `CSRF_TRUSTED_ORIGINS` to the real HTTPS origin(s)
- Set the database password
- Set `BOT_API_TOKEN` to match the Discord bot
- Set `TMDB_READ_ACCESS_TOKEN`
- Set `DJANGO_SECURE_SSL_REDIRECT=true` after TLS is working

After the service is installed, restart it after any environment change. For
manual management commands, load the environment into your shell:

```bash
set -a
. /etc/movieclub.env
set +a
```

Run `uv` manage commands through `nix/env` so they use the same Python and
virtualenv as development:

```bash
nix/env --command bash -c '
  set -a
  . /etc/movieclub.env
  set +a
  uv run python manage.py check
'
```

## 6. Seed the database over SSH

Do **not** copy a plaintext database dump onto the server. Stream it directly
from your local machine into `pg_restore` over SSH:

```bash
pg_dump -h 127.0.0.1 -p 5433 -U LOCAL_DB_USER -d movieclub \
  --format=custom \
  --no-owner \
  --no-privileges \
| ssh deploy@SERVER_IP \
  'pg_restore \
    --host=127.0.0.1 \
    --port=5432 \
    --username=movieclub \
    --dbname=movieclub \
    --no-owner \
    --no-privileges \
    --single-transaction \
    --exit-on-error'
```

If you already created a local dump file, stream the file without storing it on
the server:

```bash
ssh deploy@SERVER_IP \
  'pg_restore \
    --host=127.0.0.1 \
    --port=5432 \
    --username=movieclub \
    --dbname=movieclub \
    --no-owner \
    --no-privileges \
    --single-transaction \
    --exit-on-error' \
  < backups/movieclub.dump
```

The `deploy` user’s `~/.pgpass` supplies the password without putting it on the
command line. If a restore fails and you need to retry, recreate the empty
database first:

```bash
sudo -u postgres dropdb movieclub
sudo -u postgres createdb -O movieclub movieclub
```

## 7. Run migrations and collect static files

On the server, from `/srv/movie-club`, run the management commands inside the
same Nix environment and with the production environment loaded:

```bash
nix/env --command bash -c '
  set -a
  . /etc/movieclub.env
  set +a
  uv run python manage.py migrate
  uv run python manage.py collectstatic --noinput
'
sudo chmod -R a+rX /srv/movie-club/staticfiles
```

The final permission change lets Nginx read the collected static files.

If the restored database does not contain a usable admin account:

```bash
nix/env --command bash -c '
  set -a
  . /etc/movieclub.env
  set +a
  uv run python manage.py createsuperuser
'
```

The public charts are already stored under `static/charts/` and are copied by
`collectstatic`. Chart generation dependencies are not needed in production.

## 8. Configure Gunicorn and systemd

Install the service file:

```bash
sudo cp deploy/movieclub.service /etc/systemd/system/movieclub.service
sudo systemctl daemon-reload
sudo systemctl enable --now movieclub
```

Check that it is running:

```bash
sudo systemctl status movieclub --no-pager
curl -I http://127.0.0.1:8000/
```

Follow logs:

```bash
sudo journalctl -u movieclub -f
```

The service binds only to `127.0.0.1:8000`; it is not exposed directly to the
internet. It runs the virtualenv directly, so Nix is not required at service
startup.

## 9. Configure Nginx

```bash
sudo cp deploy/nginx-movieclub.conf /etc/nginx/sites-available/movieclub
sudo ln -sf /etc/nginx/sites-available/movieclub /etc/nginx/sites-enabled/movieclub
sudo rm -f /etc/nginx/sites-enabled/default
sudoedit /etc/nginx/sites-available/movieclub
```

Replace `YOUR_DOMAIN`. If you are not using `www`, remove the `www` hostname
from `server_name` and from the Certbot command below.

Validate and reload Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Enable the firewall:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

Do not open PostgreSQL port `5432` or Gunicorn port `8000`.

## 10. Enable HTTPS

```bash
sudo certbot --nginx -d YOUR_DOMAIN -d www.YOUR_DOMAIN
```

If you are not using `www`, omit `-d www.YOUR_DOMAIN`.

Certbot will add the HTTPS server block and HTTP-to-HTTPS redirect. If you have
now enabled `DJANGO_SECURE_SSL_REDIRECT=true` in `/etc/movieclub.env`, restart
the application so it picks up the change:

```bash
sudo systemctl restart movieclub
```

Confirm the certificate renewal timer:

```bash
sudo systemctl status certbot.timer --no-pager
sudo certbot renew --dry-run
```

## 11. Verify the deployment

```bash
curl -I https://YOUR_DOMAIN/
curl -fsS https://YOUR_DOMAIN/health/
curl -fsS https://YOUR_DOMAIN/archive/ | grep -o '[0-9]* picks'
```

Also verify:

- The homepage loads the current pick
- The archive and movie detail pages load
- `/admin/` accepts an admin login
- `/api/weeks/` works with the production `BOT_API_TOKEN`
- Static charts and CSS return `200`, not `404`

Run Django’s deployment checks with the environment loaded:

```bash
nix/env --command bash -c '
  set -a
  . /etc/movieclub.env
  set +a
  uv run python manage.py check --deploy
'
```

Review any warnings. HSTS can be added at the Nginx layer after HTTPS has been
stable.

## 12. Backups

The database contains member accounts and personal data. Encrypt backups before
storing them off the Droplet.

A simple encrypted backup flow using `age`:

```bash
sudo apt install -y age
sudo mkdir -p /var/backups/movieclub
sudo chown deploy:movieclub /var/backups/movieclub
sudo chmod 750 /var/backups/movieclub
```

Generate an age keypair and keep the private key offline. Store only the public
key on the server, then create backups with:

```bash
pg_dump \
  --host=127.0.0.1 \
  --port=5432 \
  --username=movieclub \
  --dbname=movieclub \
  --format=custom \
  --no-owner \
  --no-privileges \
| age -r "$(cat /etc/movieclub-age.pub)" \
  -o "/var/backups/movieclub/movieclub-$(date +%F).dump.age"
```

Retain backups according to your needs and copy the encrypted files off the
Droplet. DigitalOcean Droplet backups are useful, but they are not a substitute
for an independently verified database backup.

## 13. Updating the application

```bash
cd /srv/movie-club
umask 022
git pull --ff-only

# Only needed when flake.nix or flake.lock changed.
nix profile upgrade --all

nix/env --command bash -c '
  set -a
  . /etc/movieclub.env
  set +a
  make sync-prod
  uv run python manage.py migrate
  uv run python manage.py collectstatic --noinput
'
sudo chmod -R a+rX /srv/movie-club/staticfiles
sudo systemctl restart movieclub
```

Reload Nginx only when its configuration changed:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 14. Rollback

For a bad application release:

```bash
cd /srv/movie-club
umask 022
git checkout PREVIOUS_COMMIT

# Only needed when flake.nix or flake.lock changed.
nix profile upgrade --all

nix/env --command bash -c '
  set -a
  . /etc/movieclub.env
  set +a
  make sync-prod
  uv run python manage.py collectstatic --noinput
'
sudo chmod -R a+rX /srv/movie-club/staticfiles
sudo systemctl restart movieclub
```

If a migration is not backward compatible, restore the last verified database
backup into a fresh database rather than attempting to reverse the migration.

## 15. Production checklist

- [ ] `DJANGO_DEBUG=false`
- [ ] Strong, unique `DJANGO_SECRET_KEY`
- [ ] Correct `DJANGO_ALLOWED_HOSTS`
- [ ] Correct `CSRF_TRUSTED_ORIGINS`
- [ ] `/etc/movieclub.env` is `640 root:movieclub`
- [ ] Nix is installed and flakes are enabled
- [ ] The `movie-club-runtime` package is installed in the deploy user’s Nix profile
- [ ] Production dependencies were installed with `nix/env --command make sync-prod`
- [ ] Database port is not publicly reachable
- [ ] Gunicorn is bound to `127.0.0.1` only
- [ ] Nginx serves `/static/` from `staticfiles/`
- [ ] HTTPS certificate is valid and auto-renewing
- [ ] `BOT_API_TOKEN` matches the Discord bot
- [ ] TMDB token is configured
- [ ] Database backups are encrypted and stored off the Droplet
- [ ] Database dumps and `.env` files are absent from Git
- [ ] `python manage.py check --deploy` has been reviewed
