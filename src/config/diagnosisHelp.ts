export interface DiagnosisHelpSection {
  title: string
  items: string[]
}

export interface DiagnosisHelp {
  title: string
  summary: string
  sourceLabel: string
  sections: DiagnosisHelpSection[]
}

export const diagnosisHelpByLabel: Record<string, DiagnosisHelp> = {
  'Vertebral osteomyelitis': {
    title: 'Vertebral osteomyelitis',
    summary: 'Infection of the vertebral bone, often involving the adjacent disc space.',
    sourceLabel: 'IDSA native vertebral osteomyelitis guideline',
    sections: [
      {
        title: 'Look for in the note',
        items: [
          'Back or neck pain that is persistent or worsening',
          'Fever, elevated ESR/CRP, bacteremia, or positive blood cultures',
          'MRI or imaging evidence of vertebral infection, discitis, or epidural abscess',
          'Staphylococcus aureus or recent bloodstream infection',
        ],
      },
      {
        title: 'Related terms',
        items: [
          'Discitis',
          'Osteodiscitis',
          'Spinal osteomyelitis',
          'Epidural abscess',
        ],
      },
      {
        title: 'Do not confuse with',
        items: [
          'Degenerative back pain without infection evidence',
          'Metastatic bone disease',
          'Nonspecific chronic pain without imaging, microbiology, or inflammatory support',
        ],
      },
    ],
  },
}
