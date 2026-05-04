# NWS Drought Indicators

This codebase was designed by SNAP for a collaboration with the National Weather Service and can be used for computing a series of "indicators" (aka indices) that may be useful in assessing drought conditions in Alaska. 

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


### Climate Data Store (CDS) API Credentials

Complete the following items to set up permissions for downloading ERA5-Land data.

 - Register for the ECWMF CDS API.
 - Store API credentials in a file called `.cdsapirc` in your `$HOME` directory.
 - Accept the Terms and Conditions of the CDS API

### Configuration

If needed, edit `./config.py` to...

 - Control the lag between the present date and the first date of data fetched by the CDS API
 - Modify the geographic bounding box
 
### Input data

Unzip the `drought_clim_data.zip` archive file somewhere and make note of this path. This folder contains some data (climatologies) that is necessary for computing the indices.

## Usage

### Environment variables

The following environment variables need to be set/modified prior to running any of the code herein, such as starting a Jupyter server or running any scripts:


### Run the processing script

Now simply run the processing script to generate the indices dataset:

`python process.py`

The new datasets - one for each interval, containing results across the grid for all indices - will be written to the `$NWS_DROUGHT_DATA_DIR/outputs` directory, with files named as such: `nws_drought_indices_<interval>day.nc`
