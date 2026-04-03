
/* SmartBin — Shared Behaviors (drop-in for all pages) */
(function(){
  const $ = (sel, root=document) => root.querySelector(sel);
  const $$ = (sel, root=document) => Array.from(root.querySelectorAll(sel));

  // ===== Highlight the active nav item
  const path = location.pathname.replace(/\/+$/,'') || '/';
  $$('.navbar a').forEach(a => {
    const href = a.getAttribute('href');
    if (!href) return;
    const normalized = href.startsWith('/') ? href : '/' + href.replace(/^\//,'');
    if (normalized === path) a.classList.add('active');
  });

  // ===== Back button (if present)
  $$('.close-btn, [data-action="back"]').forEach(b =>
    b.addEventListener('click', () => {
      if (document.referrer) history.back(); else location.href = '/';
    })
  );

  // ===== Login form validation & LEDs (login.html)
  const form = $('#loginForm');
  if (form){
    const email = $('#email');
    const pwd = $('#password');
    const emailErr = $('#emailError');
    const pwdErr = $('#passwordError');
    const capsHint = $('#capsHint');
    const submitBtn = $('#loginSubmit');
    const togglePwd = $('#togglePassword');
    const leds = [$('#led1'), $('#led2'), $('#led3')].filter(Boolean);

    const DOMAIN = 'exemple.com'; // keep as-is to match requirement

    const setInvalid = (el, invalid) => {
      el.setAttribute('aria-invalid', invalid ? 'true' : 'false');
    };

    const checkEmail = () => {
      const ok = email.value.trim().toLowerCase().endsWith('@' + DOMAIN);
      emailErr.style.display = ok ? 'none' : 'block';
      setInvalid(email, !ok);
      return ok;
    };

    const strength = (s) => {
      let score = 0;
      if (s.length >= 8) score++;
      if (/[A-Z]/.test(s) && /[a-z]/.test(s)) score++;
      if (/\d/.test(s) || /\W/.test(s)) score++;
      return score; // 0..3
    };

    const paintLEDs = (score) => {
      leds.forEach((el,i)=>{
        el.classList.remove('ok','mid','bad');
        if (score === 0){ if(i===0) el.classList.add('bad'); }
        if (score === 1){ if(i===0) el.classList.add('mid'); }
        if (score >= 2){ if(i<=1) el.classList.add('ok'); }
        if (score === 3){ if(i===2) el.classList.add('ok'); }
      });
    };

    const updatePwd = () => {
      const sc = strength(pwd.value);
      paintLEDs(sc);
      const ok = pwd.value.length >= 8;
      pwdErr.style.display = ok ? 'none' : 'block';
      setInvalid(pwd, !ok);
      return ok;
    };

    const updateSubmitState = () => {
      const ok = checkEmail() && updatePwd();
      submitBtn.disabled = !ok;
      return ok;
    };

    // events
    email.addEventListener('input', updateSubmitState);
    pwd.addEventListener('input', updateSubmitState);

    // caps lock detection
    pwd.addEventListener('keyup', (e) => {
      const caps = e.getModifierState && e.getModifierState('CapsLock');
      if (capsHint) capsHint.style.display = caps ? 'block' : 'none';
    });

    // show/hide password
    if (togglePwd){
      togglePwd.addEventListener('click', () => {
        const now = pwd.getAttribute('type') === 'password' ? 'text' : 'password';
        pwd.setAttribute('type', now);
        togglePwd.setAttribute('aria-pressed', now === 'text' ? 'true' : 'false');
        togglePwd.textContent = now === 'text' ? 'Hide' : 'Show';
      });
    }

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!updateSubmitState()){
        form.classList.remove('shake'); void form.offsetWidth; form.classList.add('shake');
        return;
      }
      submitBtn.disabled = true;
      submitBtn.textContent = 'Signing in...';
      // Simulate request
      setTimeout(()=>{
        alert('Signed in successfully!');
        submitBtn.textContent = 'Sign in';
        submitBtn.disabled = false;
      }, 700);
    });

    // restore remembered email
    const saved = localStorage.getItem('smartbin_email');
    if (saved) email.value = saved;
    $('#rememberMe')?.addEventListener('change', (e)=>{
      if (e.target.checked) localStorage.setItem('smartbin_email', email.value.trim());
      else localStorage.removeItem('smartbin_email');
    });
    email.addEventListener('blur', ()=>{
      if ($('#rememberMe')?.checked) localStorage.setItem('smartbin_email', email.value.trim());
    });

    updateSubmitState();
  }

  // ===== Settings sliders dynamic labels & sample bin bars (settings.html)
  const rangeIds = ['organic','plastic','metal','paper'];
  rangeIds.forEach(id => {
    const slider = document.getElementById(id);
    const label = document.getElementById(id+'Val');
    if (!slider || !label) return;
    const onInput = () => label.textContent = slider.value + '%';
    slider.addEventListener('input', onInput);
    onInput();
  });

  // demo: adjust bin bars if same IDs exist (progress animation)
  const fillMap = {
    organicFill: 'var(--success)',
    plasticFill: 'var(--warn)',
    metalFill: 'var(--info)',
    paperFill: 'var(--violet)'
  };
  Object.entries(fillMap).forEach(([id,color]) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.style.background = color;
    const width = el.style.width || '0%';
    el.style.width = '0%';
    requestAnimationFrame(()=>{ el.style.width = width; });
  });

  // ===== AI Detection: Screenshot button mock
  const shotBtn = $$('.btn').find(b => /screenshot/i.test(b.textContent || ''));
  if (shotBtn){
    shotBtn.addEventListener('click', () => {
      shotBtn.disabled = true;
      const original = shotBtn.textContent;
      shotBtn.textContent = 'Capturing...';
      setTimeout(() => {
        const blob = new Blob(['SmartBin screenshot placeholder'], {type:'text/plain'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'screenshot.txt';
        a.click();
        shotBtn.textContent = original;
        shotBtn.disabled = false;
      }, 600);
    });
  }

  // ===== Data Analytics: Download Logs
  const dlBtn = $$('.btn').find(b => /download\s*logs/i.test(b.textContent || ''));
  if (dlBtn){
    dlBtn.addEventListener('click', () => {
      const csv = [
        'timestamp,bin,fill_percent,material',
        '2025-11-03T09:01:00Z,1,74,organic',
        '2025-11-03T09:01:00Z,2,41,plastic',
        '2025-11-03T09:01:00Z,3,29,metal',
        '2025-11-03T09:01:00Z,4,33,paper'
      ].join('\\n');
      const blob = new Blob([csv], {type:'text/csv'});
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'smartbin_logs.csv';
      a.click();
    });
  }
})();
