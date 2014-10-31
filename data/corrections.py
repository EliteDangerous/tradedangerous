# Provides an interface for correcting star/station names that
# have changed in recent versions.

systems = {
}

stations = {
    'LOUIS DE LACAILLE PROSPECT': 'Lacaille Prospect',
    'HOPKINS HANGAR': 'Cori Terminal',
    'HOPKINS HANGER': 'Cori Terminal',
}

categories = {
    'DRUGS':            'Legal Drugs',
}

items = {
    'HYDROGEN FUELS':   'Hydrogen Fuel',
    'MARINE SUPPLIES':  'Marine Equipment',
    'TERRAIN ENRICH SYS': 'Land Enrichment Systems',
    'HEL-STATIC FURNACES': 'Microbial Furnaces',
}

def correctSystem(oldName):
    try:
        return systems[oldName.upper()]
    except KeyError:
        return oldName

def correctStation(oldName):
	try:
		return stations[oldName.upper()]
	except KeyError:
		return oldName

def correctCategory(oldName):
    try:
        return categories[oldName.upper()]
    except KeyError:
        return oldName

def correctItem(oldName):
    try:
        return items[oldName.upper()]
    except KeyError:
        return oldName
