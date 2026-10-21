const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {view}=require('../usb-driver.js');
test('missing driver is distinct from unplugged and device error',()=>{
 assert.match(view({state:'missing_driver'}).title,/已检测到|检测到主控/);
 assert.match(view({state:'missing_driver'}).detail,/自动安装并连接/);
 assert.match(view({state:'device_error',problem_code:10}).detail,/代码 10/);
 assert.match(view({state:'unplugged'}).detail,/数据传输/);
 assert.doesNotMatch(view({state:'unplugged'}).title,/未安装/);
});
test('failed diagnostics never claims that a driver is missing',()=>{
 assert.match(view({state:'unavailable'}).detail,/不能据此判断缺少驱动/);
 assert.equal(view({state:'ready'}).show,false);
 assert.equal(view({state:'missing_driver'},true).show,false);
});
test('driver assistance uses only the scoped install endpoint and never flashes, renumbers or opens serial itself',()=>{
 const source=fs.readFileSync(require.resolve('../usb-driver.js'),'utf8');
 assert(!source.includes("read('/api/connect'"));
 assert(!source.includes('/api/firmware/flash'));
 assert(!source.includes('ENROLL START'));
 assert(source.includes("read('/api/driver/install',{})"));
 assert(source.includes('silabs.com/documents/public/software/CP210x_Universal_Windows_Driver.zip'));
});
