"""Activity farewell order, isolated from live DB, TTS and robot clients."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

root=Path(__file__).resolve().parent
directory=root/'scenarios/social_activity_support'
sys.path.insert(0,str(root));sys.path.insert(0,str(directory))
spec=importlib.util.spec_from_file_location('activity_timing_scene',directory/'g1_showcase_demo.py')
scene=importlib.util.module_from_spec(spec);spec.loader.exec_module(scene)


class ActivityTimingTests(unittest.TestCase):
    def run_scene(self,fail=False):
        events=[];self.events=events;controller=Mock(done=False,state='wait_query')
        def handle(intent,text):
            if intent=='end':controller.done=True;controller.state='done'
            else:controller.state='wait_select'
            return {'action':'end' if intent=='end' else 'recommend','reply':intent+' reply'}
        controller.handle.side_effect=handle
        actions=Mock();actions.play.side_effect=lambda name,**kw:events.append(('gesture',name))
        def announce(_speech,message,**kw):
            events.append(('decision_start',message))
            if fail and message=='end':raise RuntimeError('tts failure')
            events.append(('decision_done',message))
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            for target in ('subprocess.Popen','requests.sessions.Session.request','sqlite3.connect'):
                stack.enter_context(patch(target,side_effect=AssertionError(target)))
            for name,value in {'ShowcaseController':controller,'ActivityNeedSession':Mock(),
                               'SpeechClient':Mock(),'RobotActionClient':actions,'RobotLedClient':Mock(),
                               'preflight_activity_data':None}.items():
                stack.enter_context(patch.object(scene,name,return_value=value))
            stack.enter_context(patch.object(scene,'listen_once',side_effect=['明天有什么活动','先这样吧']))
            stack.enter_context(patch.object(scene,'classify_showcase_intent',side_effect=[
                {'intent':'query','confidence':1},{'intent':'end','confidence':1}]))
            stack.enter_context(patch.object(scene,'build_decision_message',side_effect=lambda intent,result:intent))
            stack.enter_context(patch.object(scene,'announce_decision',side_effect=announce))
            stack.enter_context(patch.object(scene,'speak',side_effect=lambda _speech,text,**kw:events.append(('reply',text))))
            scene.run_scene(elder_id=1,elder_name='测试老人',dialect='mandarin',listen_seconds=4.5,
                            silence_timeout=.5,state_timeout=180,announce_decisions=True,no_llm=True,
                            robot_actions='execute',confirm_g1_actions=True,record_elder_needs=False)
        return events

    def test_wave_after_decision_and_immediately_before_farewell(self):
        events=self.run_scene()
        end=events.index(('decision_done','end'))
        self.assertEqual(events[end+1:end+3],[('gesture','goodbye'),('reply','end reply')])
        self.assertEqual([value for kind,value in events if kind=='gesture'],['greeting','present','goodbye'])

    def test_failed_announcement_never_triggers_goodbye(self):
        with self.assertRaises(RuntimeError):self.run_scene(fail=True)
        self.assertNotIn(('gesture','goodbye'),self.events)


if __name__=='__main__':unittest.main()
