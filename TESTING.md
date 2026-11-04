# Trying a pending integration safely

An integration from the queue has not been approved for the Home Assistant Marketplace (formerly HACS), so treat it as untrusted code.
It runs with full access to the Home Assistant it is installed in, including credentials and
network. The safer way to try one is a **throwaway Home Assistant in a Docker container**: it
has none of your real devices, accounts or settings, and you delete it when you are done.

This takes about ten minutes and was tested on Linux. Docker Desktop on Windows or macOS
works the same way (see the notes at the end).

## What you need

* **Docker.** [Install Docker Engine](https://docs.docker.com/engine/install/) (Linux) or
  [Docker Desktop](https://docs.docker.com/desktop/) (Windows, macOS).
* **The integration's code.** Open the repository from the search page, then use
  **Code → Download ZIP** and unzip it, or run `git clone https://github.com/OWNER/REPO.git`.
* **A test account**, if the integration talks to a cloud service. A container protects your
  Home Assistant and your files, but the integration still receives whatever login you type
  into it. Use a throwaway or secondary account when you can.

## 1. Make an empty config folder and add the integration

In the repository you downloaded, find the folder `custom_components/<name>` (it contains a
`manifest.json`). Copy that folder into a new, empty config folder:

```bash
mkdir -p ha-test-config/custom_components
cp -r REPO/custom_components/NAME ha-test-config/custom_components/
```

Never point this at your real Home Assistant config folder.

## 2. Start a throwaway Home Assistant

```bash
docker run -d --name ha-throwaway \
  -v "$PWD/ha-test-config:/config" \
  -e TZ=UTC \
  -p 8124:8123 \
  ghcr.io/home-assistant/home-assistant:stable
```

The first start downloads the [Home Assistant image](https://github.com/home-assistant/core/pkgs/container/home-assistant)
(about 1 GB) and takes a minute or two. Port **8124** is used so it cannot clash with a real
Home Assistant on port 8123; if 8124 is taken, pick another number. See the
[Home Assistant Container docs](https://www.home-assistant.io/installation/linux#install-home-assistant-container)
for background and the
[`docker run` reference](https://docs.docker.com/reference/cli/docker/container/run/) for the options.

## 3. Set it up and add the integration

1. Open <http://localhost:8124> and create a throwaway user (any name and password, nothing
   real). Skip the optional steps.
2. Go to **Settings → Devices & services → Add integration** (direct link:
   <http://localhost:8124/config/integrations/dashboard>) and search for the integration.
   If it is missing, check step 1 and run `docker restart ha-throwaway`.
3. To watch for problems: `docker logs -f ha-throwaway`. Home Assistant warns that it found a
   custom integration "which has not been tested". That is expected.

To test a change or a fresh copy of the code, replace the folder in `ha-test-config/custom_components/`
and run `docker restart ha-throwaway`.

## 4. Throw it away

```bash
docker rm -f ha-throwaway
docker run --rm -v "$PWD/ha-test-config:/config" --entrypoint sh \
  ghcr.io/home-assistant/home-assistant:stable -c 'rm -rf /config/* /config/.[!.]*'
rmdir ha-test-config
```

The second command is needed because the container creates files owned by `root`, which a
plain `rm -rf` cannot delete without `sudo`. Afterwards, change the password of any real
account you used for testing if you have any doubts about the integration, and revoke
anything you granted it.

## If you want to keep it

Once you are happy with an integration you can install it for real. Until it is in the
catalog, add it to your real Home Assistant as a custom repository: on Home Assistant 2026.11 or
newer go to **Settings → Marketplace**, select **Add from link** and enter the repository's GitHub
URL ([documentation](https://www.home-assistant.io/integrations/marketplace/#custom-repositories)).
On 2026.10 or older it is a
[custom repository in HACS](https://hacs.xyz/docs/faq/custom_repositories/).

That route asks you to connect a GitHub account, which is one more reason to use the copy-folder
method above in your throwaway instance: you never need to connect your own account to it.

## Notes and limits

* **Windows PowerShell:** write the volume as `-v "${PWD}/ha-test-config:/config"` and use
  `^`/backtick line continuations, or put each command on one line.
* **Not a perfect sandbox.** A container keeps code away from your files and your real Home
  Assistant, but it can still use the network and any credentials you give it. If a repository
  looks suspicious, read its code first or skip it.
* **Cloud services only see what you enter.** Devices on your home network are reachable from
  the container, so be careful with integrations that ask for local network access.
