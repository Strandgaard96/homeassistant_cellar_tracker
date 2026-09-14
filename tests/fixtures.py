"""Anonymised inventory rows shaped like CellarTracker TSV output.

Every value is a str: cellartracker parses with csv.DictReader, so no
type conversion has happened yet by the time our code sees the rows.
"""

def _row(**overrides):
    base = {
        "iWine": "1000001",
        "Valuation": "100.0",
        "Price": "80.0",
        "Currency": "DKK",
        "CT": "90.0",
        "Vintage": "2018",
        "Country": "France",
        "Region": "Bordeaux",
        "SubRegion": "Medoc",
        "Appellation": "Pauillac",
        "Producer": "Producer A",
        "Varietal": "Cabernet Sauvignon",
        "MasterVarietal": "Cabernet Sauvignon",
        "Type": "Red",
        "Color": "Red",
        "Category": "Dry",
        "Size": "750ml",
        "Location": "Cellar",
        "StoreName": "Store A",
    }
    base.update(overrides)
    return base


SAMPLE_ROWS = [
    _row(iWine="1", Valuation="100.0", CT="90.0"),
    _row(iWine="2", Valuation="200.0", CT="94.0"),
    _row(iWine="3", Country="Italy", Region="Tuscany", Producer="Producer B",
         Color="Red", Valuation="300.0", CT="96.0"),
    _row(iWine="4", Country="Italy", Region="Tuscany", Producer="Producer B",
         Color="White", Type="White", Valuation="", CT="88.0"),
    _row(iWine="5", Vintage="1001", Producer="Producer C",
         Valuation="400.0", CT=""),
]
