import unittest
from study2.review_school_answer import separate_stage, SchoolAnswerAmbiguous


class ParserTests(unittest.TestCase):
    def test_explicit_prefixes(self):
        for raw, stage in [('Primary School: A校', 'primary'), ('Secondary School：A校', 'secondary')]:
            with self.subTest(stage=stage):
                actual = separate_stage(raw)
                self.assertEqual(actual['school_name'], 'A校')
                self.assertEqual(actual['stage_annotation'], stage)

    def test_explicit_suffixes(self):
        for raw, stage in [('A校, primary', 'primary'), ('A校，secondary', 'secondary')]:
            with self.subTest(stage=stage):
                actual = separate_stage(raw)
                self.assertEqual(actual['school_name'], 'A校')
                self.assertEqual(actual['stage_annotation'], stage)

    def test_parentheses_phase_campus_and_school_words_are_preserved(self):
        name = 'A Primary School（第二校舍）(Secondary section)'
        self.assertEqual(separate_stage(name)['school_name'], name)
        self.assertEqual(separate_stage('Primary School: '+name)['school_name'], name)
        self.assertEqual(separate_stage(name+', primary')['school_name'], name)

    def test_unrecognized_labels_and_suffixes_are_not_removed(self):
        for name in ['Unrecognized label: A校', 'A校, middle', 'A校 (primary)', 'A校 Secondary']:
            with self.subTest(name=name):
                actual = separate_stage(name)
                self.assertEqual(actual['school_name'], name)
                self.assertEqual(actual['removed_annotations'], [])

    def test_conflicting_annotations_are_an_actual_hold(self):
        with self.assertRaisesRegex(SchoolAnswerAmbiguous, 'conflict'):
            separate_stage('Primary School: A校, secondary')

    def test_consistent_two_annotations_remain_unambiguous(self):
        actual = separate_stage('Primary School: A校, primary')
        self.assertEqual(actual['school_name'], 'A校')
        self.assertEqual(actual['stage_annotation'], 'primary')
        self.assertEqual(len(actual['removed_annotations']), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
