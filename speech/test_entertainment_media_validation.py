"""Unplayable local files cannot reach preference/next-song selection."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_entertainment_media_preferences
import local_media_library as media
from entertainment_controller import EntertainmentController


class AudioValidationTests(unittest.TestCase):
    def setUp(self):
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.directory=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.dict(media.CATEGORY_DIRS, music=self.directory))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        for name in ('01_good.mp3','02_bad.flac','03_good.mp3'):
            (self.directory/name).write_bytes(b'offline fixture')
        self.library=media.LocalMediaLibrary()

    @staticmethod
    def probe(command,**kwargs):
        bad=Path(command[-1]).name=='02_bad.flac'
        return Mock(stdout=json.dumps({'streams':[{'sample_rate':'0' if bad else '44100',
                                                 'channels':0 if bad else 2}]}))

    def test_preference_candidates_and_next_song_skip_zero_rate_flac(self):
        with patch.object(media.subprocess,'run',side_effect=self.probe) as probe, \
             patch('entertainment_controller.LocalMediaLibrary',return_value=self.library):
            controller=EntertainmentController()
            first=controller.play_category('music')
            next_song=controller.next_item()
            self.assertEqual(Path(first['play_item']['path']).name,'01_good.mp3')
            self.assertEqual(Path(next_song['play_item']['path']).name,'03_good.mp3')
            self.assertEqual([p.path.name for p in self.library.list_items('music')],
                             ['01_good.mp3','03_good.mp3'])
            self.assertEqual(probe.call_count,3,'unchanged files should not be probed again')

    def test_replaced_file_is_reprobed_and_can_become_playable(self):
        with patch.object(media.subprocess,'run',side_effect=self.probe):
            self.assertEqual(len(self.library.list_items('music')),2)
        (self.directory/'02_bad.flac').write_bytes(b'new longer audio fixture')
        valid=Mock(stdout=json.dumps({'streams':[{'sample_rate':'16000','channels':1}]}))
        with patch.object(media.subprocess,'run',return_value=valid) as probe:
            self.assertEqual(len(self.library.list_items('music')),3)
            probe.assert_called_once()

    def test_missing_stream_malformed_metadata_and_probe_failures_are_excluded(self):
        for value in ({'streams':[]},{'streams':[{'sample_rate':'0','channels':2}]},
                      {'streams':[{'sample_rate':'16000','channels':0}]}, {'streams':'invalid'}):
            with self.subTest(value=value):
                self.library._audio_probe_cache.clear()
                with patch.object(media.subprocess,'run',return_value=Mock(stdout=json.dumps(value))):
                    self.assertEqual(self.library.list_items('music'),[])
        for error in (FileNotFoundError('ffprobe unavailable'),
                      subprocess.TimeoutExpired('ffprobe',3),
                      subprocess.CalledProcessError(1,'ffprobe')):
            with self.subTest(error=type(error).__name__):
                self.library._audio_probe_cache.clear()
                with patch.object(media.subprocess,'run',side_effect=error):
                    self.assertEqual(self.library.list_items('music'),[])


if __name__=='__main__':unittest.main()
