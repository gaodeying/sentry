import * as React from 'react';

import SvgIcon from './svgIcon';

type Props = React.ComponentProps<typeof SvgIcon>;

const IconTaskcall = React.forwardRef(function IconTaskcall(
  props: Props,
  ref: React.Ref<SVGSVGElement>
) {
  return (
    <SvgIcon {...props} ref={ref}>
      <g clipPath="url(#clip0)">
        <ellipse cx="13.39" cy="3.23285" rx="1.49237" ry="1.49237" fill="#2B1D38" />
        <path
          fillRule="evenodd"
          clipRule="evenodd"
          d="M8.0839 2.8184C6.73996 2.80623 5.44405 3.30887 4.46491 4.22012C3.48597 5.13119 2.89885 6.38053 2.82332 7.70834C2.74778 9.03612 3.18945 10.3429 4.05839 11.3573C4.92752 12.3719 6.15771 13.0164 7.49439 13.1548C8.8311 13.2933 10.1693 12.9148 11.2313 12.0993C12.293 11.284 12.9965 10.0951 13.1981 8.78019C13.2868 8.20204 13.8273 7.80522 14.4055 7.89387C14.9836 7.98251 15.3804 8.52305 15.2918 9.10119C15.0071 10.958 14.0141 12.6329 12.5213 13.7793C11.0286 14.9255 9.15038 15.4558 7.27617 15.2617C5.40191 15.0675 3.67329 14.1636 2.44976 12.7352C1.22607 11.3067 0.60194 9.46343 0.708633 7.58804C0.815304 5.71267 1.64446 3.95154 3.0219 2.66961C4.39914 1.38785 6.21883 0.683321 8.10307 0.700376C8.68794 0.70567 9.15779 1.1841 9.15249 1.76897C9.1472 2.35385 8.66877 2.82369 8.0839 2.8184Z"
          fill="#2B1D38"
        />
        <path
          fillRule="evenodd"
          clipRule="evenodd"
          d="M12.1873 4.17576C12.2271 4.13985 12.2303 4.07845 12.1944 4.03862C12.1585 3.99878 12.0971 3.9956 12.0572 4.03151L11.0203 4.96631L10.0303 5.85879C9.5958 5.4963 9.03661 5.27819 8.42647 5.27819C7.04281 5.27819 5.92113 6.39987 5.92113 7.78353C5.92113 9.16719 7.04281 10.2889 8.42647 10.2889C9.81013 10.2889 10.9318 9.16719 10.9318 7.78353C10.9318 7.08023 10.642 6.44462 10.1753 5.98958L11.1504 5.11056L12.1873 4.17576Z"
          fill="#2B1D38"
        />
      </g>
      <defs>
        <clipPath id="clip0">
          <rect
            width="15.499"
            height="15.499"
            fill="white"
            transform="translate(0.250526 0.250549)"
          />
        </clipPath>
      </defs>
    </SvgIcon>
  );
});

IconTaskcall.displayName = 'IconTaskcall';

export {IconTaskcall};
