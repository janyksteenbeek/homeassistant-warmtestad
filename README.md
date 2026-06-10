# Warmtestad Sensor for Home Assistant

This integration monitors your heat usage from the [Warmtestad](https://warmtestad.nl/)
customer portal in Home Assistant. It logs in with your portal email and password
and exposes your cumulative heat consumption (in GJ) as an energy sensor.

Warmtestad is a provider of energy and heat services in the Netherlands. This
integration is unofficial and not affiliated with Warmtestad.

> **Heads up — the portal was completely rebuilt.** In 2026 Warmtestad migrated
> `mijn.warmtestad.nl` to the **ZeroFriction** platform, an ASP.NET Core **Blazor
> Server** app. The old REST API this integration used (bearer token + JSON
> endpoints) no longer exists, and there is **no public/JSON API** anymore — the
> data is only delivered over a Blazor **SignalR** circuit using the binary
> *blazorpack* protocol. This integration now reverse-engineers that flow. See
> [How it works](#how-it-works) below. Because the protocol is undocumented and
> binary, this client is inherently fragile to future portal changes.

## Installation

1. Copy `custom_components/warmtestad` into your Home Assistant
   `config/custom_components/` directory (or install via HACS).
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration**, search for
   **Warmtestad**, and enter the **email** and **password** you use to log in to
   `mijn.warmtestad.nl`.

That's it — you no longer need to look up portfolio/connection/asset/channel IDs.
Existing configurations from older versions are migrated automatically.

## How it works

The portal no longer exposes an API, so the integration drives the Blazor
circuit the same way the browser does (there is **no** HTTP form POST for login —
that turned out to be a red herring; the form is interactive and submits over
the circuit):

1. `GET /account/login` for the `<!--Blazor:{...}-->` server component markers.
2. `POST /_blazor/negotiate` to obtain a SignalR connection token.
3. Open a WebSocket to `/_blazor` and perform the *blazorpack* handshake.
4. `StartCircuit(...)`; the server streams **render batches** (a binary
   RenderTree format). We parse the string table, the 20-byte frame records and
   the diff section to find the login form's event handler ids and — crucially —
   the `componentId` that owns each input.
5. Dispatch browser events over the circuit (`BeginInvokeDotNetFromJS` →
   `DispatchEventAsync`): fill the email and password inputs (the bound value
   travels in `eventFieldInfo.fieldValue` with the owning `componentId`), then
   submit the form. Wrong credentials render an inline *"…email or password was
   wrong"* message; success navigates to `/login?key=<guid>`, which sets the
   auth cookie.
6. Boot the circuit again for `/consumption` and read the rendered `… GJ`
   consumption value out of the render-batch strings.

The relevant code lives in
[`custom_components/warmtestad/blazor_client.py`](custom_components/warmtestad/blazor_client.py).
The boot, render-batch parsing, event dispatch and credential-rejection
detection are all verified against the live portal; the post-login navigation
and consumption read should be confirmed with a real account via the probe
below.

## Developing / troubleshooting the portal client

Because the protocol is reverse-engineered and binary, it may need tweaking when
the portal changes. A standalone probe script lets you exercise the client
directly with your own credentials, outside Home Assistant:

```bash
pip install aiohttp msgpack
WARMTESTAD_EMAIL='you@example.com' WARMTESTAD_PASSWORD='secret' \
    python scripts/probe.py -v --dump
```

It prints the login result and the consumption value, lists every `… GJ` string
it found, and (with `--dump`) writes the raw render batches to
`warmtestad_batches.bin` for offline inspection. This is the fastest way to
diagnose a broken login or a changed data layout.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file
for details.

## Security

If you discover any security-related issues, please email
[security@janyk.dev](mailto:security@janyk.dev) instead of using the issue
tracker.
