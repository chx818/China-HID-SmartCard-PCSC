import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

pe = pefile.PE('dcrf32.dll')
image_base = pe.OPTIONAL_HEADER.ImageBase

exports = {}
for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
    if exp.address:
        exports[image_base + exp.address] = exp.name.decode() if exp.name else f'ord_{exp.ordinal}'

text_sec = None
for s in pe.sections:
    if b'.text' in s.Name:
        text_sec = s
        break

code = text_sec.get_data()
code_va = image_base + text_sec.VirtualAddress

md = Cs(CS_ARCH_X86, CS_MODE_32)
instructions = list(md.disasm(code, code_va))

dispatchers = [0x10002A40, 0x1000C300]

call_sites = []
for idx, ins in enumerate(instructions):
    if ins.mnemonic == 'call':
        try:
            target = int(ins.op_str, 16)
            if target in dispatchers:
                call_sites.append((idx, ins, target))
        except:
            pass

print(f'Found {len(call_sites)} calls to dispatchers')

results = []
for idx, ins, target in call_sites:
    func_name = 'unknown'
    for back_addr in range(ins.address, max(code_va, ins.address - 0x1000), -1):
        if back_addr in exports:
            func_name = f"{exports[back_addr]}+0x{ins.address - back_addr:X}"
            break
    
    pushes = []
    for k in range(idx - 1, max(0, idx - 10), -1):
        prev = instructions[k]
        if prev.mnemonic == 'push':
            try:
                val = int(prev.op_str, 16) if prev.op_str.startswith('0x') else int(prev.op_str)
                pushes.append((prev.address, val))
            except:
                pushes.append((prev.address, prev.op_str))
        elif prev.mnemonic in ['ret', 'call']:
            break
            
    results.append((func_name, hex(ins.address), hex(target), pushes))

header = f"{'Function':35} {'Call VA':12} {'Dispatcher':12} {'Arguments Pushed'}"
print(header)
print('-' * len(header))
seen = set()
for func, cva, disp, pushes in results:
    p_str = ', '.join(f'0x{v:X}' if isinstance(v, int) else str(v) for _, v in pushes)
    key = (func.split('+')[0], p_str)
    if key not in seen:
        seen.add(key)
        print(f"{func:35} {cva:12} {disp:12} {p_str}")
