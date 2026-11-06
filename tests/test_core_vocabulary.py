"""Hermes -> Core vocabulary normalisation (names must match Core's seeded
reference tables exactly; Core matches them case-insensitively by name)."""
import unittest

from app.integrations.core_vocabulary import (
    core_employment_types,
    core_experience_level,
    core_visa_types,
    split_location,
)

CORE_EMPLOYMENT_TYPES = {
    'Full-Time/Permanent', 'Contract', 'Contract to Hire', 'Freelance', 'Part-Time', 'Corp to Corp(C2C)', 'W2', '1099',
}
CORE_EXPERIENCE_LEVELS = {
    'Entry Level (0-2 years)', 'Mid Level (3-5 years)', 'Senior Level (6-10 years)', 'Lead Principal (10+ years)',
}
CORE_VISA_TYPES = {'H-1B', 'Green Card', 'US Citizen', 'EAD', 'L1', 'OPT', 'CPT'}


class EmploymentTests(unittest.TestCase):
    def test_every_hermes_value_maps_into_core_names(self):
        for raw in ('Contract', 'Contract to Hire', 'Full-time', 'Part-time', 'W2'):
            names, dropped = core_employment_types(raw)
            self.assertEqual(dropped, [], raw)
            self.assertTrue(set(names) <= CORE_EMPLOYMENT_TYPES, (raw, names))

    def test_full_time_uses_cores_name(self):
        self.assertEqual(core_employment_types('Full-time')[0], ['Full-Time/Permanent'])

    def test_unknown_is_dropped_not_guessed(self):
        self.assertEqual(core_employment_types('Gig'), ([], ['Gig']))
        self.assertEqual(core_employment_types(None), ([], []))

    def test_stated_rate_basis_adds_engagement_type(self):
        self.assertEqual(core_employment_types('Contract', basis='C2C')[0], ['Contract', 'Corp to Corp(C2C)'])


class ExperienceTests(unittest.TestCase):
    def test_buckets_are_core_level_names(self):
        for years, expected in ((0, 'Entry Level (0-2 years)'), (2, 'Entry Level (0-2 years)'), (4, 'Mid Level (3-5 years)'),
                                (8, 'Senior Level (6-10 years)'), (10, 'Lead Principal (10+ years)'), (15, 'Lead Principal (10+ years)')):
            level = core_experience_level(years)
            self.assertEqual(level, expected)
            self.assertIn(level, CORE_EXPERIENCE_LEVELS)

    def test_missing_or_bad_is_none(self):
        self.assertIsNone(core_experience_level(None))
        self.assertIsNone(core_experience_level('n/a'))


class VisaTests(unittest.TestCase):
    def test_mapped_to_core_names(self):
        self.assertEqual(core_visa_types('H1B')[0], ['H-1B'])
        names, _ = core_visa_types('Green Card, US Citizen')
        self.assertEqual(names, ['Green Card', 'US Citizen'])
        self.assertTrue(set(names) <= CORE_VISA_TYPES)

    def test_no_core_equivalent_is_dropped(self):
        self.assertEqual(core_visa_types('Any Visa'), ([], ['Any Visa']))
        self.assertEqual(core_visa_types('TN Visa'), ([], ['TN Visa']))


class LocationTests(unittest.TestCase):
    def test_city_state_full_name(self):
        self.assertEqual(split_location('Dallas, TX'), {'city': 'Dallas', 'state': 'Texas'})
        self.assertEqual(split_location('Austin, Texas'), {'city': 'Austin', 'state': 'Texas'})
        self.assertEqual(split_location('Dallas TX'), {'city': 'Dallas', 'state': 'Texas'})

    def test_mode_prefix_does_not_pollute_city(self):
        self.assertEqual(split_location('Hybrid - Dallas, TX'), {'work_mode': 'HYBRID', 'city': 'Dallas', 'state': 'Texas'})
        self.assertEqual(split_location('Burlington, MA (100% Onsite)'),
                         {'work_mode': 'ONSITE', 'city': 'Burlington', 'state': 'Massachusetts'})

    def test_remote_only_has_no_city(self):
        self.assertEqual(split_location('Remote'), {'work_mode': 'REMOTE'})
        self.assertEqual(split_location('Fully Remote'), {'work_mode': 'REMOTE'})

    def test_unrecognised_state_is_omitted(self):
        self.assertNotIn('state', split_location('Toronto, ON'))


if __name__ == '__main__':
    unittest.main()
