# Warmtestad Sensor for Home Assistant

This integration allows you to monitor heat usage data from the Warmtestad service using Home Assistant. It fetches and updates heat usage data from the Warmtestad client portal using your email and password.

Warmtestad is a provider of energy and heat services in the Netherlands. See [warmtestad.nl](https://warmtestad.nl/) for more information. This integration is not affiliated with Warmtestad and is an unofficial implementation.


## Installation

1. **Clone the Repository:**

```bash
git clone https://github.com/janyksteenbeek/homeassistant-warmtestad.git
```

2. **Copy Files:**

Copy the integration files into your Home Assistant custom components directory. Typically, this is located at `config/custom_components/`.

```bash
cp -r homeassistant-warmtestad/custom_components/warmtestad /config/custom_components/
```

3. **Restart Home Assistant:**

Restart Home Assistant to load the new integration.

## Configuration

### YAML Configuration

Add the following to your `configuration.yaml` file:

```yaml
sensor:
  - platform: warmtestad
    email: YOUR_EMAIL
    password: YOUR_PASSWORD
    portfolio_id: YOUR_PORTFOLIO_ID
    connection_id: YOUR_CONNECTION_ID
    asset_id: YOUR_ASSET_ID
    channel_id: YOUR_CHANNEL_ID
```

Replace the placeholders with your actual Warmtestad credentials and IDs. 

You can find the required IDs by inspecting the Warmtestad client portal. Navigate to the heat usage data you want to monitor and check the network tab in DevTools. Look for the API requests and extract the IDs from the `indexes` endpoint. The URL should look like this:


```
https://portalwarmtestad-prd.azurewebsites.net/users/USER_ID/portfolios/PORTFOLIO_ID/connections/CONNECTION_ID/assets/ASSET_ID/channels/CHANNEL_ID/indexes?page=1
```


You can also configure the sensor via the Home Assistant UI:

1. Navigate to `Configuration` > `Integrations`.
2. Click on `Add Integration` and search for "Warmtestad".
3. Enter the required credentials and IDs when prompted.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.


## Security

If you discover any security-related issues, please email [security@janyk.dev](mailto:security@janyk.dev) instead of using the
issue tracker. All security vulnerabilities will be promptly addressed.
