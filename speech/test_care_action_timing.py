"""Care invite timing without SDK writes, ASR/TTS, sleeping or DB access."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parent
SCENE=ROOT/'scenarios/care_consultation_support'
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(SCENE))
spec=importlib.util.spec_from_file_location('care_timing_scene',SCENE/'g1_voice_demo.py')
scene=importlib.util.module_from_spec(spec)
spec.loader.exec_module(scene)


class CareActionTimingTests(unittest.TestCase):
    def run_fake_scene(self,status='started',transfer=None):
        events=[]
        first={'reply':'首次护理回复','state':'CONSULTING','round_no':1}
        if transfer:first['transfer_to']=transfer
        consultation=Mock(round_no=1)
        consultation.start.return_value=first
        consultation.handle_user_text.side_effect=[
            {'reply':'第二轮护理回复','state':'CONSULTING','round_no':2},
            {'reply':'结束回复','state':'ENDED','end_reason':'user_requested','round_no':3},
        ]
        def action(_actions,name,**_):
            events.append(('action',name))
            return {'status':status}
        def speak(_speech,text,**_):events.append(('speak',text))
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            for target in ('subprocess.Popen','requests.sessions.Session.request','sqlite3.connect'):
                stack.enter_context(patch(target,side_effect=AssertionError('offline test attempted '+target)))
            values={
                'get_elderly':{'name':'离线测试'},'create_session':123,
                'SpeechClient':Mock(),'RobotLedClient':Mock(),'RobotActionClient':Mock(),
                'CareConsultation':consultation,'is_care_trigger':True,
                'save_user_message':None,'save_assistant_message':None,'update_session_context':None,
                'finalize_care_session':{},'build_memory_announcement':{},
                'build_showcase_profile_announcement':{},'announce_decision':None,
            }
            for name,value in values.items():
                stack.enter_context(patch.object(scene,name,return_value=value))
            stack.enter_context(patch.object(scene,'listen',side_effect=['胳膊酸','持续三天','先这样吧']))
            stack.enter_context(patch.object(scene,'trigger_robot_action',side_effect=action))
            stack.enter_context(patch.object(scene,'speak',side_effect=speak))
            stack.enter_context(patch.object(scene.time,'sleep',side_effect=lambda seconds:events.append(('wait',seconds))))
            scene.run_scene(elderly_id=1,max_rounds=20,dialect='mandarin',listen_seconds=6,
                announce_decisions=False,showcase=True,robot_actions='execute',confirm_g1_actions=True,
                robot_leds='off')
        return events

    def test_first_invite_starts_before_reply_with_one_lead(self):
        events=self.run_fake_scene()
        index=events.index(('action','acknowledge'))
        self.assertEqual(events[index:index+3],[('action','acknowledge'),('wait',1.5),('speak','首次护理回复')])
        self.assertEqual(events.count(('action','acknowledge')),1)
        self.assertEqual(events.count(('wait',1.5)),1)
        self.assertIn(('speak','第二轮护理回复'),events)
        self.assertEqual(events[-1],('action','goodbye'))

    def test_inactive_or_failed_invite_adds_no_delay(self):
        for status in ('off','dry_run','busy','confirmation_required','failed'):
            with self.subTest(status=status):
                events=self.run_fake_scene(status)
                self.assertFalse(any(kind=='wait' for kind,_ in events))

    def test_transfer_does_not_trigger_invite_or_wait(self):
        events=self.run_fake_scene(transfer='CONTACT_FAMILY')
        self.assertFalse(any(kind in ('action','wait') for kind,_ in events))


if __name__=='__main__':unittest.main()
