"""Course titles from the checked-in authoritative seeds/scraped/course_*.json.

Packaged with the app so Docker does not need the full seed dataset.
"""
COURSE_TITLES = {'766': 'Bachelor of Computer Science', '1807': 'Bachelor of Information Technology', '1838': 'Bachelor of Business Information Systems'}

COURSE_TITLES.update({"1802": "Bachelor of Computer Science (Dean\'s Scholar)", "765": "Bachelor of Computer Science (Honours)"})
