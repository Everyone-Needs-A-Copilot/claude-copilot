"""Offline controls for trusted workflow code versus unverified release bytes.

The production verifier has compiled roots. Only a private test copy substitutes
ephemeral public roots; workflow execution clears its optional narrowing inputs.
No actual repository, remote service, credential or signing key is used.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml

ROOT=Path(__file__).resolve().parents[2]


class ReleaseWorkflowAuthority(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence=Path(tempfile.mkdtemp(prefix='cc-release-authority-')).resolve()
        print(f'release workflow authority evidence: {cls.evidence}')

    def setUp(self):
        self.scratch=Path(tempfile.mkdtemp(dir=self.evidence)).resolve()
        self.env=dict(os.environ,GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull)
        self.env.pop('FOUNDATION_RELEASE_PUBLIC_KEY',None)
        self.env.pop('FOUNDATION_RELEASE_PRINCIPAL',None)

    def run_command(self,args,cwd=None,env=None,check=True):
        result=subprocess.run([str(x) for x in args],cwd=cwd,env=env or self.env,text=True,capture_output=True,timeout=60)
        if check:
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return result

    def fixture(self):
        self.work=self.scratch/'candidate'
        self.run_command(['git','init','-q','-b','main',self.work])
        self.key=self.scratch/'authorized-key'
        self.run_command(['ssh-keygen','-q','-t','ed25519','-N','','-f',self.key])
        for key,value in [('user.name','Fixture'),('user.email','fixture@example.invalid'),('gpg.format','ssh'),('user.signingkey',str(self.key)),('core.hooksPath',os.devnull)]:
            self.run_command(['git','config',key,value],cwd=self.work)
        original=(ROOT/'scripts/verify-foundation-release.sh').read_text()
        roots=re.findall(r'"(ssh-ed25519 AAAA[^"\n]+)"',original)
        self.assertEqual(len(roots),2)
        public=' '.join(self.key.with_suffix('.pub').read_text().split()[:2])
        fixture_verifier=original
        for root in roots:
            fixture_verifier=fixture_verifier.replace(root,public)
        self.trusted=self.scratch/'trusted-workflow-verifier.sh'
        self.trusted.write_text(fixture_verifier)
        (self.work/'payload').write_text('authorized bytes\n')
        self.run_command(['git','add','payload'],cwd=self.work)
        self.run_command(['git','commit','-q','-S','-m','authorized source'],cwd=self.work)
        self.commit=self.run_command(['git','rev-parse','HEAD'],cwd=self.work).stdout.strip()
        self.run_command(['git','tag','-s','-m','authorized tag','v1.2.3'],cwd=self.work)

    def verify(self,tag,commit):
        return self.run_command(['bash',self.trusted,self.work,tag,commit],check=False)

    def test_protected_dispatch_and_exact_workflow_checkout_are_executable_guards(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/cc-macos-release.yml').read_text())
        job=workflow['jobs']['package']
        self.assertEqual(job['environment'],'release')
        self.assertIn("github.ref == 'refs/heads/main'",job['if'])
        self.assertIn('github.ref_protected',job['if'])
        checkout=next(s for s in job['steps'] if str(s.get('uses','')).startswith('actions/checkout@'))
        self.assertEqual(checkout['with']['ref'],'${{ github.workflow_sha }}')
        guard=job['steps'][0]['run']
        for ref,protected,allowed in [('refs/heads/main','true',True),('refs/heads/feature','true',False),('refs/tags/v1.2.3','true',False),('refs/heads/main','false',False)]:
            result=self.run_command(['bash','-c',guard],env=dict(self.env,RELEASE_WORKFLOW_REF=ref,RELEASE_WORKFLOW_PROTECTED=protected),check=False)
            self.assertEqual(result.returncode==0,allowed,(ref,protected,result.stderr))
        proof=next(s for s in job['steps'] if s.get('name')=='Verify the exact integrated release source')
        self.assertIn('unset FOUNDATION_RELEASE_PUBLIC_KEY FOUNDATION_RELEASE_PRINCIPAL',proof['run'])
        self.assertIn('"$SOURCE_REF" "$SOURCE_COMMIT"',proof['run'])
        self.assertNotIn('${{ inputs.',proof['run'])
        steps=job['steps']
        proof_index=steps.index(proof)
        for step in steps[:proof_index]:
            self.assertNotIn('secrets.',str(step))
            self.assertNotIn('pip install',step.get('run',''))
        self.assertLess(proof_index,next(i for i,s in enumerate(steps) if 'secrets.APPLE_CERTIFICATE' in str(s)))

    def test_authorized_signed_candidate_still_passes(self):
        self.fixture()
        result=self.verify('v1.2.3',self.commit)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_unsigned_candidate_cannot_supply_its_own_verifier_or_roots(self):
        self.fixture()
        scripts=self.work/'scripts'; scripts.mkdir()
        malicious=scripts/'verify-foundation-release.sh'
        marker=self.scratch/'candidate-verifier-called'
        malicious.write_text('#!/bin/bash\nprintf "candidate accepted\\n" >> "$CANDIDATE_MARKER"\nexit 0\n')
        attacker=self.scratch/'attacker-key'
        self.run_command(['ssh-keygen','-q','-t','ed25519','-N','','-f',attacker])
        (self.work/'allowed_signers').write_text(attacker.with_suffix('.pub').read_text())
        self.run_command(['git','add','scripts','allowed_signers'],cwd=self.work)
        self.run_command(['git','-c','commit.gpgsign=false','commit','-q','-m','unsigned attacker candidate'],cwd=self.work)
        unsigned=self.run_command(['git','rev-parse','HEAD'],cwd=self.work).stdout.strip()
        self.run_command(['git','-c','tag.gpgsign=false','tag','-a','-m','unsigned tag','v1.2.4'],cwd=self.work)
        bypass=self.run_command(['bash',malicious,self.work,'v1.2.4',unsigned],env=dict(self.env,CANDIDATE_MARKER=str(marker)),check=False)
        self.assertEqual(bypass.returncode,0)
        before=marker.read_bytes()
        self.assertNotEqual(self.verify('v1.2.4',unsigned).returncode,0)
        self.assertEqual(marker.read_bytes(),before)
        # A key file inside the candidate cannot authorize a second signer.
        self.run_command(['git','config','user.signingkey',attacker],cwd=self.work)
        self.run_command(['git','commit','-q','-S','--allow-empty','-m','attacker signed source'],cwd=self.work)
        wrong=self.run_command(['git','rev-parse','HEAD'],cwd=self.work).stdout.strip()
        self.run_command(['git','tag','-s','-m','attacker signed tag','v1.2.5'],cwd=self.work)
        self.assertNotEqual(self.verify('v1.2.5',wrong).returncode,0)
        self.assertEqual(marker.read_bytes(),before)


if __name__=='__main__':
    unittest.main(verbosity=2)
