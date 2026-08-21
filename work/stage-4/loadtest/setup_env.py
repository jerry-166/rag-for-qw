import requests, json
B='http://localhost:8003'
tok=requests.post(B+'/api/auth/login',data={'username':'admin','password':'admin123'}).json()['access_token']
H={'Authorization':f'Bearer {tok}'}
# register loadtester
r=requests.post(B+'/api/auth/register',json={'username':'loadtester','password':'Loadtest#123','email':'loadtester@test.local'})
print('register:',r.status_code,r.text[:200])
r=requests.post(B+'/api/auth/login',data={'username':'loadtester','password':'Loadtest#123'})
print('login:',r.status_code)
lt=r.json()['access_token']
H2={'Authorization':f'Bearer {lt}','X-Request-ID':'stage4-loadtest-setup'}
# KBs: no-op enhancers + real enhancers
r=requests.post(B+'/api/knowledge-bases',headers=H2,json={'kb_name':'loadtest-noop','description':'Stage4 压测-增强全关','enhancers':[],'chunk_strategy':'recursive'})
print('kb-noop:',r.status_code,r.text[:300])
r=requests.post(B+'/api/knowledge-bases',headers=H2,json={'kb_name':'loadtest-real','description':'Stage4 压测-真实增强采样','enhancers':['sub_question','summary'],'chunk_strategy':'recursive'})
print('kb-real:',r.status_code,r.text[:300])
json.dump({'loadtester_token':lt,'admin_token':tok},open('tokens.json','w'))
