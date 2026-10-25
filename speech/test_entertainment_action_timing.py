"""Scene-level gesture/speech order with no cloud, media, DB or robot access."""
import contextlib
import io
import unittest
from unittest.mock import Mock,patch

from test_entertainment_media_preferences import Library,load_scene

scene=load_scene('g1_showcase_demo')


class EntertainmentTimingTests(unittest.TestCase):
    def run_scene(self, *, announce_enabled=True, decision_error=False):
        events=[];now=[0.0]
        def add(kind,value):events.append((kind,value,now[0]))
        def sleep(seconds):now[0]+=seconds
        def announce(_speech,intent,*,enabled):
            if not enabled:return
            add('decision_start',intent)
            if decision_error and intent=='end':raise RuntimeError('announcement failed')
            add('decision_done',intent)
        player=Mock();player.playing=False
        player.is_playing.side_effect=lambda:player.playing
        player.play.side_effect=lambda *_:setattr(player,'playing',True)
        player.stop.side_effect=lambda **_:setattr(player,'playing',False)
        live=Mock()
        live.get_event.side_effect=[{'kind':'transcript','text':value} for value in
                                   ('机器人，放点音乐','机器人，换一首','机器人，换成新闻',
                                    '机器人，换成戏曲','机器人，不听了')]
        needs=Mock();needs.preferred_item.return_value=None
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            for target in ('subprocess.Popen','requests.sessions.Session.request','sqlite3.connect'):
                stack.enter_context(patch(target,side_effect=AssertionError('offline access: '+target)))
            stack.enter_context(patch('entertainment_controller.LocalMediaLibrary',return_value=Library()))
            values={'SpeechClient':Mock(),'EntertainmentNeedSession':needs,'G1MediaPlayer':player,
                    'RobotActionClient':Mock(),'RobotLedClient':Mock(),'preflight_media':None,
                    'start_live_asr':live}
            for name,value in values.items():stack.enter_context(patch.object(scene,name,return_value=value))
            stack.enter_context(patch.object(scene,'trigger_robot_action',side_effect=lambda _client,name,**kw:add('gesture',name)))
            stack.enter_context(patch.object(scene,'speak_interaction',side_effect=lambda _speech,text:add('reply',text)))
            stack.enter_context(patch.object(scene,'announce',side_effect=announce))
            stack.enter_context(patch.object(scene.time,'sleep',side_effect=sleep))
            try:
                scene.run_scene(listen_seconds=4.5,state_timeout=60,announce_decisions=announce_enabled,
                                use_llm=False,robot_actions='execute',confirm_g1_actions=True,
                                elderly_id=1,record_elder_needs=False,robot_leds='off')
            except RuntimeError:
                if not decision_error:raise
        return events

    def test_present_later_preserves_speech_and_end_wave_follows_announcement(self):
        events=self.run_scene()
        gestures=[event for event in events if event[0]=='gesture']
        self.assertEqual([event[1] for event in gestures],['greeting','present','goodbye'])
        self.assertEqual(next(event[2] for event in gestures if event[1]=='present'),0.5)
        self.assertEqual(next(event[2] for event in events if event[:2]==('decision_start','play_music')),1.5)
        done=next(i for i,event in enumerate(events) if event[:2]==('decision_done','end'))
        self.assertEqual(events[done+1][:2],('gesture','goodbye'))
        self.assertEqual(events[done+2][:2],('reply',scene.INTERACTION_REPLIES[scene.END]))

    def test_no_decision_mode_still_waves_at_farewell_only(self):
        events=self.run_scene(announce_enabled=False)
        wave=next(i for i,event in enumerate(events) if event[:2]==('gesture','goodbye'))
        self.assertEqual(events[wave+1][:2],('reply',scene.INTERACTION_REPLIES[scene.END]))
        self.assertFalse(any(event[0].startswith('decision') for event in events))

    def test_failed_end_announcement_never_starts_premature_wave(self):
        events=self.run_scene(decision_error=True)
        self.assertFalse(any(event[:2]==('gesture','goodbye') for event in events))


if __name__=='__main__':unittest.main()
