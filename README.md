<h2 align="center">
  <a href="https://www.cellartracker.com/"><img src="./img/ct_logo.png" alt="Cellar Tracker logo" width="200"></a>
  <br>
  <i>Home Assistant Cellar Tracker custom integration</i>
  <br>
</h2>

<p align="center">
  <a href="https://github.com/custom-components/hacs"><img src="https://img.shields.io/badge/HACS-Custom-orange.svg"></a>
</p>

The `cellar tracker` implementation allows you to integrate your [Cellar Tracker](https://www.cellartracker.com/) data in Home Assistant.

# Disclaimer
This is an unofficial integration of Cellar Tracker for Home Assistant, the developer and the contributors are not, in any way, affiliated to CellarTracker! LLC.

"CellarTracker!" is a trademark of CellarTracker! LLC

# Requirements
- Cellar Tracker account - https://cellartracker.com
- HACS: Home Assistant Community Store - https://hacs.xyz/
- [Mushroom Cards](https://github.com/piitaya/lovelace-mushroom) - Available in HACS
- [Flex Table Card](https://github.com/custom-cards/flex-table-card/) - Available in HACS
- **(Optional)** [card-mod](https://github.com/thomasloven/lovelace-card-mod) - Available in HACS - not required by either dashboard YAML below, but handy for further styling
- **(Optional)** secrets.yaml - https://www.home-assistant.io/docs/configuration/secrets/

# Installation
The integration should be available in HACS under Custom Integration, if that is not the case, just add manually the repository:

![HACS Adding a repository](./img/hacs_1.png)

- **Repository:** https://github.com/ahoernecke/ha_cellar_tracker
- **Category:** Integration

# Configuration

Go to **Settings → Devices & services → Add integration**, search for **Cellar Tracker**, and sign in with your CellarTracker! username and password. The login is checked against CellarTracker! before the integration is added.

Only one CellarTracker! account can be added per Home Assistant instance.

## Options

Open the integration and choose **Configure** to change the update interval (in seconds, default 3600, minimum 30). The integration reloads with the new interval when you save.

## Changed password

If CellarTracker! stops accepting your password, Home Assistant shows a **Re-authenticate** prompt for the integration. Enter the new password there; your entities are kept.

## Upgrading from YAML

Earlier versions were configured with a `cellar_tracker:` block in `configuration.yaml`. Delete that block (and the `cellar_tracker_username`/`cellar_tracker_password` entries in `secrets.yaml` if nothing else uses them), restart Home Assistant, then add the integration from the UI as above. Existing entity IDs, renames and areas are kept, because the sensors' unique IDs have not changed. If the block is left in place, Home Assistant shows a repair notice and ignores it.

## Entities

The integration creates 47 entities from your inventory:

| Shape | Count | Example entity ID | Notes |
| --- | --- | --- | --- |
| Per-value sensor (low-cardinality dimension) | 34 | `sensor.cellar_tracker_country_france` | One sensor per distinct value of Country, Type, Size, Category, Location, Color. |
| Slice sensor (long-tail dimension) | 9 | `sensor.cellar_tracker_by_producer` | State is the number of distinct values; the full breakdown lives in the `items` list attribute (capped at the top 100 entries by count). |
| Scalar | 4 | `sensor.cellar_tracker_total_value` | Cellar-wide totals: total bottles, total value, average value, average score. |

# Dashboard visualization

> **Breaking change:** entity IDs changed in this release. Every dashboard card built against the previous entity model will stop working and must be rebuilt using the new entity IDs below. Obsolete entities from the previous model are removed automatically from the entity registry on the first start after upgrading — no manual cleanup needed.

![CellarTracker! Dashboard](./img/dashboard.png)

To create a new dashboard for CellarTracker! go to Configuration -> Dashboards -> Add a new dashboard (the following is just a suggestion)

![CellarTracker! Dashboard Creation](./img/new_dashboard.png)

## To populate your Dashboard

Paste each view below into a new dashboard's raw configuration editor (three-dot menu -> Edit Dashboard -> three-dot menu -> Edit in YAML). Requires the Mushroom, Flex Table Card and card-mod frontend resources listed under Requirements above.

**Overview** — from [`docs/dashboard/overview.yaml`](./docs/dashboard/overview.yaml):

```yaml
title: Overview
path: overview
cards:
  - type: custom:mushroom-chips-card
    chips:
      - type: entity
        entity: sensor.cellar_tracker_total_bottles
        icon: mdi:bottle-wine
      - type: entity
        entity: sensor.cellar_tracker_total_value
        icon: mdi:cash
      - type: entity
        entity: sensor.cellar_tracker_average_score
        icon: mdi:star
      - type: entity
        entity: sensor.cellar_tracker_by_producer
        icon: mdi:account-group

  - type: statistics-graph
    title: Cellar value
    entities:
      - sensor.cellar_tracker_total_value
    stat_types:
      - state
    days_to_show: 365
    period: day
```

`stat_types: [state]` is required: `total_value` has `state_class: total`, which produces `state`/`sum` statistics, not `mean`.

**Explore** — from [`docs/dashboard/explore.yaml`](./docs/dashboard/explore.yaml), one flex-table card per long-tail dimension, reading the `items` attribute of each slice sensor:

```yaml
title: Explore
path: explore
cards:
  - type: custom:flex-table-card
    title: By producer
    entities:
      include: sensor.cellar_tracker_by_producer
    max_rows: 50
    sort_by: count-
    columns:
      - name: Producer
        id: name
        data: items.name
      - name: Bottles
        id: count
        data: items.count
      - name: Avg value
        id: value_avg
        data: items.value_avg
        modify: parseFloat(x).toFixed(0)
      - name: Avg score
        id: score_avg
        data: items.score_avg
        modify: "x === null ? '-' : parseFloat(x).toFixed(1)"

  - type: custom:flex-table-card
    title: By region
    entities:
      include: sensor.cellar_tracker_by_region
    sort_by: count-
    columns:
      - name: Region
        id: name
        data: items.name
      - name: Bottles
        id: count
        data: items.count
      - name: Avg value
        id: value_avg
        data: items.value_avg
        modify: parseFloat(x).toFixed(0)
      - name: Avg score
        id: score_avg
        data: items.score_avg
        modify: "x === null ? '-' : parseFloat(x).toFixed(1)"

  - type: custom:flex-table-card
    title: By score band
    entities:
      include: sensor.cellar_tracker_by_score_band
    sort_by: name+
    columns:
      - name: Band
        id: name
        data: items.name
      - name: Bottles
        id: count
        data: items.count
      - name: Avg value
        id: value_avg
        data: items.value_avg
        modify: parseFloat(x).toFixed(0)
```

`by_producer` shows the top 50 producers by count (the `items` attribute itself is capped by the integration; the sensor's `items_total` attribute carries the full distinct-value count so a card can show e.g. "50 of N"). Explicit column `id`s are required: with list-of-dict expansion, `sort_by` needs them. `sensor.cellar_tracker_by_producer`, `sensor.cellar_tracker_by_region` and `sensor.cellar_tracker_by_score_band` can be swapped for any of the other slice sensors (`by_store`, `by_appellation`, `by_varietal`, `by_mastervarietal`, `by_vintage`, `by_subregion`) using the same column layout.

# Contribute
Feel free to contribute by opening a PR, issue on this project