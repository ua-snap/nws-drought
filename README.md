# Drought Indicators

This codebase computes a series of "drought indicators" for assessing drought conditions in Alaska. 

It generates a dataset of seven indicators computed over retrospective intervals - "summary intervals" - from a supplied reference date with the following lengths (in days): 7, 30, 60, 90, 180, 365. The summary interval is the $n$-length sequence of days preceding and ending with the reference date $d_0$, for each interval size $n$. The seven indicators are:

* `tp`: Total precipitation. $\sum p_i$ for all days $i$ in the summary interval.
* `pntp`: Percent of normal total precipitation. $\frac{\sum p_j}{\sum pclim_j} * 100$ for all days-of-year $j$ in the summary interval, where $pclim_j$ is the climatological daily total precip value for day-of-year $j$.
* `swe`: Snow water equivalent. Mean daily snow water equivalent for the summary interval. I.e., $\frac{1}{n}\sum swe_i$ for all days $i=1, 2, ..., n$ in the summary interval. 
* `pnswe`: Percent of normal snow water equivalent. $\frac{\frac{1}{n}\sum swe_j}{\frac{1}{n}\sum sweclim_j} * 100$ for all $n$ days-of-year $j$ in the summary interval, and all matching days-of-year $j$ for the climatological daily swe values ( $sweclim$ ).
* `spi`: Standardized Precipitation Index. 
  * Let $F_{X_{nj}}$ be the cumulative distribution function of a gamma variable $X_{nj}$, for some summary interval $n$ (and having length $n$) preceding, and including as the final element, some reference date $d_0$ with day-of-year $j$, distributed as $Gamma(\alpha_{nj}, \beta_{nj})$ where $\alpha_{nj}$ and $\beta_{nj}$ have been estimated using the set of rolling total precipitation values ${p_{nj1}, p_{nj2}, ..., p_{njk}}$, computed using a window of size $n$ for the $k$ years in the climatology period. I.e., $p_{nj1} = \sum\limits^{n}_{i=1}p_i$ for the first year of the climatology period. Then the standardized precipitation index for this summary interval is given by  

  $$spi_{ij} = F_{norm}^{-1}(F_{X_{ij}}(p_{ij0}))$$
  * Where $F_{norm}^{-1}$ is the probability point function (a.k.a. quantile function) for the standard normal distribution and $p_{ij0}$ is the total precipitation for the summary interval of interest.

* `spei`: Standarized precipitation evapotranspiration index. Same as `spi`, but using water budget instead of total precipitation, which is computed as total precipitation minus total evapotranspiration (Note, in ERA5-Land, this variable is just called potential evaporation).
* `smd`: Soil moisture deficit. $\frac{\frac{1}{n}\sum swvlclim_j - \frac{1}{n}\sum swvl_j}{\frac{1}{n}\sum swvlclim_j} * 100$ for all days-of-year $j$ in the summary interval, where $swvl$ is the volumetric soil water content for the reference year, and $swvlclim$ is the climatological mean. Note, $swvl$ and $swvlclim$ are computed as a weighted average of the top two soil layers based on depth, so $swvl = (swvl_1 * 0.25) + (swvl_2 * 0.75)$.

## Setup

### Configuration
If needed, edit `./config.py` to...
 - Control the lag between the present date and the first date of data fetched by the CDS API
 - Modify the geographic bounding box
 - Modify the set of summary intervals over which the drought indicators are computed
 - Modify the weights used to combine the soil moisture layers
 - Modify the offset applied to the water budget

### Climate Data Store (CDS) API Credentials
Complete the following items to set up permissions for downloading ERA5-Land data.
 - Register for the ECWMF CDS API.
 - Store API credentials in a file called `.cdsapirc` in your `$HOME` directory.
 - Accept the Terms and Conditions of the CDS API

### Baseline Reference Data
Ensure that the baseline reference data is available at a known path with read permissions. These data (climatologies, gamma parameters, etc.) are required for computing drought indicators. 

## Usage

### Environment Variables
- Set `INDICES_DIR` to control the destination to which the results will be written. Default is `nws-drought/drought_ouputs`.
- Set `CLIM_DIR` to control the destination that holds the baseline reference data (i.e. the climatologies and gamma parameters). Default is `nws-drought/baseline_data`.

### Pipeline Execution
Each pipeline run will require the execution of the following two scripts:

```sh
python pipeline_download.py
python pipeline_run.py
```

A drought indicator netCDF dataset, one file per summary interval, will be written to the `INDICES_DIR` directory. Each file contains results for all indices for the entire area of interest. `pipeline_run.py` names outputs `drought_indices_<summary_interval>day_<YYYY>_<MM>_<DD>.nc`. Plotting scripts expect exactly one dated file per interval listed in `INTERVALS` in `config.py`.

### Plotting maps (`data_viz/`)

Run scripts from the repository root so `INDICES_DIR` (`drought_outputs/` by default) resolves. Figures are saved under **`data_viz/figures/`**, regardless of the current working directory.

| Directory | Contents |
|-----------|----------|
| `figures/by_indicator/<scope>/` | One indicator compared across all summary intervals (`total_precipitation.png`, `spi.png`, …) |
| `figures/by_summary_interval/<scope>/` | All seven indicators on one grid per interval (`7day.png`, `30day.png`, …) |
| `figures/by_summary_interval_five_panel/<scope>/` | Five indicators per interval (omits total precipitation and SWE) |

`<scope>` is either `full_domain` or a regional subset name (`interior_alaska`, `southeast_alaska`, `southwest_alaska`).

- **`plot_<variable>.py`** — writes to `figures/by_indicator/<scope>/`.
- **`plot_by_interval.py`** — writes to `figures/by_summary_interval/<scope>/`.
- **`plot_by_interval_no_tp_swe.py`** — writes to `figures/by_summary_interval_five_panel/<scope>/`.
- **`plot_all.py`** — runs every script above for the full domain and all three regional subsets (36 figures total). Use `--full-domain-only`, `--regions-only`, or `--region <name>` to narrow scope.

Shared discrete colors, categorical bin labels, and human-readable indicator titles (`indicator_title`, `panel_title`, `colorbar_axis_label`) live in **`data_viz/plot_scales.py`** (SPI/SPEI bins follow the USDM SPI legend).

#### Zoomed regional subsets

Any plotting script accepts **`--region <name>`** to zoom to a 64×64 grid-cell window (~576 km per side at ~9 km resolution). Regional figures use the same directory layout as full-domain plots, with `<scope>` set to the region name instead of `full_domain`.

| Region | Center | Coverage (approx.) |
|--------|--------|--------------------|
| `interior_alaska` | 64.5°N, 147°W | Central Interior / Fairbanks area |
| `southeast_alaska` | 58.3°N, 134.4°W | Alaska Panhandle |
| `southwest_alaska` | 60.8°N, 161.8°W | Yukon–Kuskokwim delta (Bethel) |

```sh
python data_viz/plot_all.py                              # full domain + all regions
python data_viz/plot_spi.py --region southeast_alaska
python data_viz/plot_by_interval.py --region southwest_alaska
python data_viz/plot_all.py --region interior_alaska     # one region only
```

Community markers are drawn from **`data_viz/communities_ak_filtered.json`** for all three regions (four labeled communities each). Region definitions and slice logic live in **`data_viz/region_subset.py`**.
