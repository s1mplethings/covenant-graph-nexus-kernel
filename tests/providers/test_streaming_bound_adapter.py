import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from cgkn.providers.streaming_bound_adapter import BoundProviderRoute, invoke_stream_via_bound_opener


class FakeUpstream(io.BytesIO):
    status=200
    headers={'Content-Type':'text/event-stream'}
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


class TestBound(unittest.TestCase):
    def test_correct_model_uses_only_supplied_bound_opener(self):
        seen=[]
        def bound_open(request):
            seen.append(request)
            body=json.loads(request.data)
            self.assertTrue(body['stream'])
            self.assertEqual(body['model'],'deepseek-chat')
            self.assertEqual(request.get_full_url(),'https://api.deepseek.com/v1/chat/completions')
            self.assertIn('application/json',request.get_header('Content-type'))
            items=[
                {'id':'c1','model':'deepseek-chat','choices':[{'index':0,'delta':{'content':'{}'},'finish_reason':None}]},
                {'id':'c1','model':'deepseek-chat','choices':[{'index':0,'delta':{},'finish_reason':'stop'}], 'usage':{'prompt_tokens':2,'completion_tokens':3}},
            ]
            data=b''.join(b'data: '+json.dumps(row).encode()+b'\n\n' for row in items)+b'data: [DONE]\n\n'
            return FakeUpstream(data)
        route=BoundProviderRoute('deepseek','https://api.deepseek.com/v1','deepseek-chat')
        result=invoke_stream_via_bound_opener(route=route,token='private-token',bound_open=bound_open,
                upstream_chat_payload={'model':'deepseek-chat','messages':[{'role':'user','content':'x'}]})
        self.assertEqual(result.text,'{}')
        self.assertEqual(len(seen),1)
        self.assertIn('private-token',seen[0].get_header('Authorization'))

    def test_route_mismatch_fails_before_open(self):
        route=BoundProviderRoute('qwen','https://dashscope.aliyuncs.com/compatible-mode/v1','qwen-plus')
        def should_not_open(_):self.fail('network must not be called')
        with self.assertRaises(ValueError):
            invoke_stream_via_bound_opener(route=route,token='secret',bound_open=should_not_open,
                  upstream_chat_payload={'model':'deepseek-chat','messages':[]})

    def test_no_http_url_and_no_outside_provider(self):
        for provider,url in [('qwen','http://api.test/v1'),('grok','https://api.x.ai/v1')]:
            with self.assertRaises(ValueError):BoundProviderRoute(provider,url,'model')


if __name__=='__main__':unittest.main()
