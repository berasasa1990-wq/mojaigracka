const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(__dirname+'/static/account-auth.js','utf8');
function setup(responses){
  let handler,feedback;const calls=[],navigations=[];
  const input={value:'old-token'};
  const form={dataset:{authCsrfUrl:'/nalog/csrf/'},action:'https://shop.test/nalog/prijava/',prepend(node){feedback=node;},querySelector(){return input;},addEventListener(name,fn){handler=fn;}};
  vm.runInNewContext(source,{
    document:{querySelectorAll(){return [form];},createElement(){return {setAttribute(){},hidden:true};}},
    location:{href:form.action,origin:'https://shop.test',assign(url){navigations.push(url);}},
    URL,FormData:class{append(){}},DOMParser:class{parseFromString(){return {querySelectorAll(){return [{textContent:'E-mail ili lozinka nisu ispravni.'}];}};}},
    async fetch(url,options){calls.push({url,options});return responses.shift();},
  });
  return {submit:()=>handler({preventDefault(){},submitter:{disabled:false}}),calls,navigations,feedback:()=>feedback};
}
const token=()=>({ok:true,redirected:false,json:async()=>({csrfToken:'A'.repeat(64)})});
const csrf=()=>({status:403,headers:{get:()=> '1'}});
const success=()=>({ok:true,status:200,redirected:true,url:'https://shop.test/nalog/',headers:{get:()=>null}});
test('one retry on stale CSRF then successful navigation',async()=>{
 const app=setup([token(),csrf(),token(),success()]);await app.submit();
 assert.equal(app.calls.length,4);assert.equal(app.navigations.length,1);
});
test('two CSRF failures stop, never loop',async()=>{
 const app=setup([token(),csrf(),token(),csrf()]);await app.submit();
 assert.equal(app.calls.length,4);assert.equal(app.navigations.length,0);assert.match(app.feedback().textContent,/kolačić/);
});
test('invalid credentials never trigger a login retry',async()=>{
 const app=setup([token(),{ok:true,status:200,redirected:false,headers:{get:()=>null},text:async()=>'<form>error</form>'}]);await app.submit();
 assert.equal(app.calls.length,2);assert.match(app.feedback().textContent,/lozinka/);
});
test('token fetch failure preserves form and shows error',async()=>{
 const app=setup([{ok:false}]);await app.submit();assert.equal(app.calls.length,1);assert.equal(app.feedback().hidden,false);
});
